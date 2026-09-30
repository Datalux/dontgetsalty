from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import game, models
from ..broadcaster import broadcast_room_state
from ..connection_manager import manager
from ..db import SessionLocal

router = APIRouter()


@router.websocket("/ws/{code}")
async def room_ws(websocket: WebSocket, code: str, token: str | None = None):
    code = code.upper()
    db = SessionLocal()
    try:
        player = game.get_player_by_token(db, token) if token else None
        room = game.get_room_by_code(db, code)
        if player is None or room is None or player.room_id != room.id:
            await websocket.close(code=4001)
            return

        player.connected = True
        player.disconnected_at = None
        player_id = player.id
        db.commit()
    finally:
        db.close()

    await manager.connect(code, websocket, player_id)
    await broadcast_room_state(code)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(code, websocket)
        remaining = manager.player_ids(code)
        if player_id not in remaining:
            db = SessionLocal()
            try:
                fresh_player = db.get(models.Player, player_id)
                if fresh_player is not None:
                    fresh_player.connected = False
                    fresh_player.disconnected_at = models.utcnow()
                    db.commit()
            finally:
                db.close()
        await broadcast_room_state(code)
