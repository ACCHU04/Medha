import logging
from uuid import UUID

from fastapi import WebSocket

from ..models import CaseEvent, GpsPoint, Vital
from ..schemas.case_event import CaseEventOut
from ..schemas.gps import GpsOut
from ..schemas.vital import VitalOut

logger = logging.getLogger(__name__)


class ConnectionManager:
    """In-memory fan-out per case. Single-process only; Redis for multi-instance later."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = {}

    def subscribe(self, case_id: UUID, websocket: WebSocket) -> None:
        key = str(case_id)
        self._subscribers.setdefault(key, set()).add(websocket)

    def unsubscribe(self, case_id: UUID, websocket: WebSocket) -> None:
        key = str(case_id)
        sockets = self._subscribers.get(key)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            self._subscribers.pop(key, None)

    async def broadcast(self, case_id: UUID, payload: dict) -> None:
        key = str(case_id)
        sockets = self._subscribers.get(key)
        if not sockets:
            return
        dead = []
        for websocket in list(sockets):
            try:
                await websocket.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.append(websocket)
        for websocket in dead:
            sockets.discard(websocket)
        if not sockets:
            self._subscribers.pop(key, None)


manager = ConnectionManager()


async def broadcast_vital(case_id: UUID, vital: Vital) -> None:
    payload = VitalOut.model_validate(vital).model_dump(mode="json")
    await manager.broadcast(case_id, payload)


async def broadcast_case_event(
    case_id: UUID,
    event: CaseEvent,
    case: dict | None = None,
) -> None:
    """Fan out a lifecycle/acceptance event. ``case`` should be the serialized
    CaseOut payload (destination/acceptance fields), not a raw ORM object."""
    payload = {
        "type": "event",
        "event": CaseEventOut.model_validate(event).model_dump(mode="json"),
        "case": case,
    }
    await manager.broadcast(case_id, payload)


async def broadcast_gps(case_id: UUID, point: GpsPoint) -> None:
    payload = {
        "type": "gps",
        "gps": GpsOut.model_validate(point).model_dump(mode="json"),
    }
    await manager.broadcast(case_id, payload)
