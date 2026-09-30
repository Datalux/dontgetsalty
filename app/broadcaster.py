from . import game
from .connection_manager import manager
from .db import SessionLocal


async def broadcast_room_state(room_code: str) -> None:
    """Push each connected player their own personalised (anonymised) state."""
    connections = manager.rooms.get(room_code)
    if not connections:
        return

    db = SessionLocal()
    try:
        room = game.get_room_by_code(db, room_code)
        if room is None:
            return

        players_by_id = {p.id: p for p in room.players}

        for websocket, player_id in list(connections.items()):
            player = players_by_id.get(player_id)
            if player is None:
                continue
            try:
                await websocket.send_json(game.public_state(db, room, player))
            except Exception:
                manager.disconnect(room_code, websocket)
    finally:
        db.close()
