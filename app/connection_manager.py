from fastapi import WebSocket


class ConnectionManager:
    """Keeps track of WebSocket connections per room, in process memory.

    This only works for a single-process deployment: there is no cross-process
    pub/sub, which is an accepted tradeoff for a small party game (see README).
    """

    def __init__(self) -> None:
        # room_code -> {websocket: player_id}
        self.rooms: dict[str, dict[WebSocket, int]] = {}

    async def connect(self, room_code: str, websocket: WebSocket, player_id: int) -> None:
        await websocket.accept()
        self.rooms.setdefault(room_code, {})[websocket] = player_id

    def disconnect(self, room_code: str, websocket: WebSocket) -> None:
        connections = self.rooms.get(room_code)
        if not connections:
            return
        connections.pop(websocket, None)
        if not connections:
            del self.rooms[room_code]

    def player_ids(self, room_code: str) -> set[int]:
        return set(self.rooms.get(room_code, {}).values())


manager = ConnectionManager()
