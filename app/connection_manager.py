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

    async def kick(self, room_code: str, player_id: int) -> None:
        """Tell every socket belonging to `player_id` they were removed, then
        close it, so the removed player's client can leave cleanly instead of
        silently ending up with a dead token."""
        connections = self.rooms.get(room_code, {})
        for websocket, pid in list(connections.items()):
            if pid != player_id:
                continue
            connections.pop(websocket, None)
            try:
                await websocket.send_json({"removed": True})
                await websocket.close()
            except Exception:
                pass
        if room_code in self.rooms and not self.rooms[room_code]:
            del self.rooms[room_code]

    def player_ids(self, room_code: str) -> set[int]:
        return set(self.rooms.get(room_code, {}).values())


manager = ConnectionManager()
