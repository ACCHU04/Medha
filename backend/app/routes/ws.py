from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import EmergencyCase, User
from ..models.enums import UserRole
from ..security import decode_access_token
from ..services.realtime import manager

router = APIRouter()

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


def _negotiated_protocol(websocket: WebSocket) -> str | None:
    protocols = websocket.headers.get("sec-websocket-protocol")
    if not protocols:
        return None
    for protocol in protocols.split(","):
        protocol = protocol.strip()
        if not protocol:
            continue
        if protocol.startswith("bearer ") or protocol.count(".") == 2:
            return protocol
    return None


def _extract_token(websocket: WebSocket) -> str | None:
    protocol = _negotiated_protocol(websocket)
    if protocol is not None:
        if protocol.startswith("bearer "):
            return protocol[len("bearer "):].strip()
        return protocol
    token = websocket.query_params.get("token")
    return token if token else None


def _authorize(
    websocket: WebSocket, db: Session
) -> tuple[User, EmergencyCase] | int:
    token = _extract_token(websocket)
    if token is None:
        return CLOSE_UNAUTHENTICATED
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        return CLOSE_UNAUTHENTICATED
    except jwt.InvalidTokenError:
        return CLOSE_UNAUTHENTICATED

    user_id = payload.get("sub")
    if user_id is None:
        return CLOSE_UNAUTHENTICATED
    user = db.get(User, user_id)
    if user is None:
        return CLOSE_UNAUTHENTICATED

    try:
        case_id = UUID(websocket.path_params["case_id"])
    except (KeyError, ValueError):
        return CLOSE_NOT_FOUND
    case = db.get(EmergencyCase, case_id)
    if case is None:
        return CLOSE_NOT_FOUND

    if user.role == UserRole.paramedic and case.created_by_id != user.id:
        return CLOSE_FORBIDDEN
    return user, case


@router.websocket("/ws/cases/{case_id}/vitals")
async def vitals_stream(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> None:
    result = _authorize(websocket, db)
    db.rollback()
    if isinstance(result, int):
        await websocket.close(code=result)
        return

    user, case = result
    await websocket.accept(subprotocol=_negotiated_protocol(websocket))
    manager.subscribe(case.id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(case.id, websocket)


@router.websocket("/ws/cases/{case_id}/events")
async def events_stream(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> None:
    result = _authorize(websocket, db)
    db.rollback()
    if isinstance(result, int):
        await websocket.close(code=result)
        return

    user, case = result
    await websocket.accept(subprotocol=_negotiated_protocol(websocket))
    manager.subscribe(case.id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(case.id, websocket)
