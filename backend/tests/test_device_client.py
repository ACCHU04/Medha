import uuid

import pytest

from app.schemas.sync import AppliedOp, SkippedOp, SyncPushResponse
from app.services.sync.device import (
    FAILED,
    PENDING,
    SYNCED,
    AmbulanceDevice,
    SQLiteLocalStore,
    TransportError,
)
from app.services.sync.hlc import HlcClock, HlcTimestamp

DEVICE = str(uuid.uuid4())


def _oid():
    return str(uuid.uuid4())


class OfflineTransport:
    def push(self, batch):
        raise TransportError("simulated network loss")


class AppliedTransport:
    def __init__(self, skip: set[str] | None = None):
        self.skip = skip or set()
        self.pushed = 0

    def push(self, batch):
        self.pushed += 1
        applied, skipped = [], []
        for op in batch:
            if str(op.id) in self.skip:
                skipped.append(SkippedOp(id=op.id, entity=op.entity, reason="validation failed"))
            else:
                applied.append(AppliedOp(id=op.id, entity=op.entity))
        return SyncPushResponse(applied=applied, skipped=skipped)


@pytest.fixture()
def store(tmp_path):
    return SQLiteLocalStore(tmp_path / "outbox.sqlite")


@pytest.fixture()
def clock():
    return HlcClock(DEVICE)


# ---- Store durability ----


def test_outbox_survives_reopen(tmp_path, clock):
    path = tmp_path / "outbox.sqlite"
    store = SQLiteLocalStore(path)
    op_id = _oid()
    hlc = clock.now()
    store.enqueue(op_id, "upsert", "vital", hlc, {"case_id": "x"})
    store.close()

    reopened = SQLiteLocalStore(path)
    pending = reopened.pending()
    assert len(pending) == 1
    assert pending[0]["id"] == op_id
    assert pending[0]["entity"] == "vital"
    assert pending[0]["status"] == PENDING
    reopened.close()


def test_enqueue_replace_same_id(store, clock):
    op_id = _oid()
    hlc = clock.now()
    store.enqueue(op_id, "upsert", "vital", hlc, {"case_id": "x"})
    store.enqueue(op_id, "upsert", "vital", hlc, {"case_id": "y"})
    pending = store.pending()
    assert len(pending) == 1
    assert pending[0]["payload"] == '{"case_id": "y"}'


# ---- Flush: offline behavior ----


def test_flush_offline_bumps_attempts_and_stays_pending(tmp_path, clock):
    store = SQLiteLocalStore(tmp_path / "o.sqlite")
    device = AmbulanceDevice(store, OfflineTransport(), clock, max_attempts=3)
    op_id = _oid()
    device.record("vital", op_id, {"case_id": "x"})

    result = device.flush()
    assert result.online is False
    assert result.synced == []
    row = store.pending()[0]
    assert row["status"] == PENDING
    assert row["attempts"] == 1


def test_dlq_after_max_attempts(tmp_path, clock):
    store = SQLiteLocalStore(tmp_path / "o.sqlite")
    device = AmbulanceDevice(store, OfflineTransport(), clock, max_attempts=2)
    device.record("vital", _oid(), {"case_id": "x"})

    device.flush()
    device.flush()
    counts = store.counts()
    assert counts.get(FAILED) == 1
    assert counts.get(PENDING) is None


def test_offline_flush_does_not_lose_data(tmp_path, clock):
    store = SQLiteLocalStore(tmp_path / "o.sqlite")
    device = AmbulanceDevice(store, OfflineTransport(), clock, max_attempts=10)
    for _ in range(5):
        device.record("vital", _oid(), {"case_id": "x"})
    device.flush()
    assert device.queue_size() == 5


# ---- Flush: success ----


def test_flush_success_marks_synced(tmp_path, clock):
    store = SQLiteLocalStore(tmp_path / "o.sqlite")
    transport = AppliedTransport()
    device = AmbulanceDevice(store, transport, clock)
    p1, v1 = _oid(), _oid()
    device.record("patient", p1, {"name": "A"})
    device.record("vital", v1, {"case_id": "c1"})

    result = device.flush()
    assert result.online is True
    assert sorted(result.synced) == sorted([p1, v1])
    counts = store.counts()
    assert counts.get(SYNCED) == 2
    assert device.queue_size() == 0


def test_server_skip_moves_to_dlq(tmp_path, clock):
    store = SQLiteLocalStore(tmp_path / "o.sqlite")
    good, bad = _oid(), _oid()
    transport = AppliedTransport(skip={bad})
    device = AmbulanceDevice(store, transport, clock)
    device.record("vital", good, {"case_id": "x"})
    device.record("vital", bad, {"case_id": "x"})

    result = device.flush()
    assert sorted(result.synced) == [good]
    assert result.skipped == [bad]
    counts = store.counts()
    assert counts.get(SYNCED) == 1
    assert counts.get(FAILED) == 1
    assert store.pending() == []


def test_flush_empty_is_online_noop(tmp_path, clock):
    store = SQLiteLocalStore(tmp_path / "o.sqlite")
    device = AmbulanceDevice(store, AppliedTransport(), clock)
    result = device.flush()
    assert result.online is True
    assert result.synced == []


# ---- Recording ----


def test_record_embeds_device_id(clock):
    store = SQLiteLocalStore(":memory:")
    device = AmbulanceDevice(store, AppliedTransport(), clock)
    hlc = device.record("vital", _oid(), {"case_id": "c1"})
    assert HlcTimestamp.from_string(hlc).device_id == DEVICE
    assert device.queue_size() == 1


def test_backoff_grows_then_caps():
    store = SQLiteLocalStore(":memory:")
    device = AmbulanceDevice(store, AppliedTransport(), HlcClock(DEVICE))
    assert device.next_backoff_seconds(1) == 0.0
    assert device.next_backoff_seconds(2) == 2.0
    assert device.next_backoff_seconds(3) == 4.0
    assert device.next_backoff_seconds(8) == 60.0
