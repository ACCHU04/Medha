"""Offline-first ambulance device: local SQLite outbox + flush orchestrator.

The device captures patient/case/vital/event ops into a durable local outbox
while disconnected, then flushes them to the server via ``/api/v1/sync/push``.
Transient transport failures increment a per-op attempt counter with exponential
backoff; ops that exceed the max attempts (or are permanently rejected by the
server) move to a dead-letter state.
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol
from uuid import UUID

import httpx

from ...schemas.sync import SyncOp, SyncPushRequest, SyncPushResponse
from .hlc import HlcClock

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id          TEXT PRIMARY KEY,
    op          TEXT NOT NULL,
    entity      TEXT NOT NULL,
    hlc         TEXT NOT NULL,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_outbox_status ON outbox (status, created_at);
"""

PENDING = "pending"
SYNCED = "synced"
FAILED = "failed"


class TransportError(Exception):
    """Transient connectivity failure — ops stay pending for retry."""


class SyncTransport(Protocol):
    def push(self, batch: list[SyncOp]) -> SyncPushResponse: ...


class HttpSyncTransport:
    """Real transport over HTTP (used by the on-vehicle client in production)."""

    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    def push(self, batch: list[SyncOp]) -> SyncPushResponse:
        try:
            response = self._client.post(
                "/api/v1/sync/push",
                json=SyncPushRequest(batch=batch).model_dump(mode="json"),
            )
            response.raise_for_status()
            return SyncPushResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise TransportError(str(exc)) from exc


class SQLiteLocalStore:
    """Durable local outbox. Survives process restarts (disk-backed)."""

    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def enqueue(self, op_id: str, op: str, entity: str, hlc: str, payload: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO outbox (id, op, entity, hlc, payload, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (op_id, op, entity, hlc, json.dumps(payload), PENDING),
        )
        self._conn.commit()

    def pending(self) -> list[sqlite3.Row]:
        rows = self._conn.execute(
            "SELECT * FROM outbox WHERE status = ? ORDER BY created_at, id",
            (PENDING,),
        ).fetchall()
        return list(rows)

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM outbox GROUP BY status"
        ).fetchall()
        return {row["status"]: row["n"] for row in rows}

    def _set_status(self, op_id: str, status: str, error: str | None = None) -> None:
        if error is None:
            self._conn.execute(
                "UPDATE outbox SET status = ?, last_error = NULL WHERE id = ?",
                (status, op_id),
            )
        else:
            self._conn.execute(
                "UPDATE outbox SET status = ?, last_error = ? WHERE id = ?",
                (status, error, op_id),
            )
        self._conn.commit()

    def mark_synced(self, op_id: str) -> None:
        self._set_status(op_id, SYNCED)

    def mark_failed(self, op_id: str, error: str) -> None:
        self._set_status(op_id, FAILED, error)

    def bump_attempt(self, op_id: str, error: str, max_attempts: int) -> bool:
        """Increment the retry counter. Returns True when moved to DLQ."""
        self._conn.execute(
            "UPDATE outbox SET attempts = attempts + 1, last_error = ? WHERE id = ?",
            (error, op_id),
        )
        row = self._conn.execute(
            "SELECT attempts FROM outbox WHERE id = ?", (op_id,)
        ).fetchone()
        self._conn.commit()
        if row is not None and row["attempts"] >= max_attempts:
            self._set_status(op_id, FAILED, error)
            return True
        return False

    def to_batch(self, rows: list[sqlite3.Row]) -> list[SyncOp]:
        batch = []
        for row in rows:
            batch.append(
                SyncOp(
                    op=row["op"],
                    entity=row["entity"],
                    id=UUID(row["id"]),
                    device_id=UUID(_device_from_hlc(row["hlc"])),
                    hlc=row["hlc"],
                    data=json.loads(row["payload"]),
                )
            )
        return batch

    def close(self) -> None:
        self._conn.close()


def _device_from_hlc(hlc: str) -> str:
    return hlc.rsplit(":", 1)[-1]


@dataclass
class FlushResult:
    online: bool
    synced: list[str] = field(default_factory=list)
    dlq: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class AmbulanceDevice:
    """Coordinates capture + flush for one ambulance device."""

    def __init__(
        self,
        store: SQLiteLocalStore,
        transport: SyncTransport,
        clock: HlcClock,
        max_attempts: int = 5,
        backoff_base_seconds: float = 1.0,
        backoff_cap_seconds: float = 60.0,
    ) -> None:
        self._store = store
        self._transport = transport
        self._clock = clock
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._backoff_cap = backoff_cap_seconds

    @property
    def device_id(self) -> str:
        return self._clock.device_id

    def record(self, entity: str, op_id: str, data: dict) -> str:
        hlc = self._clock.now()
        self._store.enqueue(op_id, "upsert", entity, hlc, data)
        return hlc

    def queue_size(self) -> int:
        return self._store.counts().get(PENDING, 0)

    def next_backoff_seconds(self, attempts: int) -> float:
        if attempts <= 1:
            return 0.0
        delay = self._backoff_base * (2 ** (attempts - 1))
        return min(delay, self._backoff_cap)

    def flush(self) -> FlushResult:
        """Push all pending ops. Offline => attempts bump + backoff; DLQ at cap."""
        pending = self._store.pending()
        if not pending:
            return FlushResult(online=True)
        try:
            response = self._transport.push(self._store.to_batch(pending))
        except TransportError as exc:
            for row in pending:
                self._store.bump_attempt(row["id"], f"transport: {exc}", self._max_attempts)
            return FlushResult(online=False)

        applied_ids = {str(item.id) for item in response.applied}
        skipped_ids = {str(item.id) for item in response.skipped}
        result = FlushResult(online=True)
        for row in pending:
            if row["id"] in applied_ids:
                self._store.mark_synced(row["id"])
                result.synced.append(row["id"])
            elif row["id"] in skipped_ids:
                reason = next(
                    (item.reason for item in response.skipped if str(item.id) == row["id"]),
                    "rejected",
                )
                self._store.mark_failed(row["id"], reason)
                result.skipped.append(row["id"])
            else:
                # Neither applied nor skipped (e.g. protocol drift) — treat as permanent.
                self._store.mark_failed(row["id"], "unacknowledged")
                result.skipped.append(row["id"])
        return result
