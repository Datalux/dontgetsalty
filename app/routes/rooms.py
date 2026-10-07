from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import game, models, schemas
from ..broadcaster import broadcast_room_state
from ..connection_manager import manager
from ..db import get_db

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def get_current_player(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.Player:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    player = game.get_player_by_token(db, token) if token else None
    if player is None:
        raise HTTPException(status_code=401, detail="Token non valido.")
    return player


def get_room_for_player(
    code: str,
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
) -> models.Room:
    room = game.get_room_by_code(db, code)
    if room is None or player.room_id != room.id:
        raise HTTPException(status_code=404, detail="Stanza non trovata.")
    return room


@router.post("")
def create_room(body: schemas.CreateRoomRequest, db: Session = Depends(get_db)):
    room, player = game.create_room(db, body.nickname)
    return {
        "room_code": room.code,
        "player_token": player.token,
        "player_id": player.id,
    }


@router.post("/{code}/join")
def join_room(code: str, body: schemas.JoinRoomRequest, db: Session = Depends(get_db)):
    try:
        room, player = game.join_room(db, code, body.nickname)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "room_code": room.code,
        "player_token": player.token,
        "player_id": player.id,
    }


@router.get("/{code}/state")
def get_state(room: models.Room = Depends(get_room_for_player), player: models.Player = Depends(get_current_player), db: Session = Depends(get_db)):
    return game.public_state(db, room, player)


@router.post("/{code}/start")
async def start(
    body: schemas.StartRequest,
    room: models.Room = Depends(get_room_for_player),
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    try:
        game.start_game(db, room, player, body.rounds)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_room_state(room.code)
    return game.public_state(db, room, player)


@router.post("/{code}/new-room")
async def new_room_from(
    room: models.Room = Depends(get_room_for_player),
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    try:
        new_host = game.start_new_room_from(db, room, player)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_room_state(room.code)
    state = game.public_state(db, room, player)
    # Only the acting host gets this: their own seat is already made, so
    # their client can jump straight in instead of joining for real like
    # everyone else does when they follow later.
    state["your_new_room"] = {
        "code": room.next_room_code,
        "player_token": new_host.token,
        "player_id": new_host.id,
    }
    return state


@router.post("/{code}/players/{player_id}/remove")
async def remove_player(
    player_id: int,
    room: models.Room = Depends(get_room_for_player),
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    try:
        game.remove_player(db, room, player, player_id)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await manager.kick(room.code, player_id)
    await broadcast_room_state(room.code)
    return game.public_state(db, room, player)


@router.get("/{code}/suggestions")
def get_room_suggestions(room: models.Room = Depends(get_room_for_player), db: Session = Depends(get_db)):
    return game.room_suggestions(db, room)


@router.post("/{code}/suggestions")
async def set_suggestions(
    body: schemas.SuggestionsRequest,
    room: models.Room = Depends(get_room_for_player),
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    try:
        game.set_suggestions_enabled(db, room, player, body.enabled)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_room_state(room.code)
    return game.public_state(db, room, player)


@router.post("/{code}/questions")
async def submit_question(
    body: schemas.QuestionRequest,
    room: models.Room = Depends(get_room_for_player),
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    try:
        game.submit_question(db, room, player, body.text)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_room_state(room.code)
    return game.public_state(db, room, player)


@router.post("/{code}/votes")
async def submit_vote(
    body: schemas.VoteRequest,
    room: models.Room = Depends(get_room_for_player),
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    try:
        game.submit_vote(db, room, player, body.target_player_id)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_room_state(room.code)
    return game.public_state(db, room, player)


@router.post("/{code}/advance")
async def advance(
    room: models.Room = Depends(get_room_for_player),
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    try:
        game.advance(db, room, player)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_room_state(room.code)
    return game.public_state(db, room, player)


@router.post("/{code}/force-start-voting")
async def force_start_voting(
    room: models.Room = Depends(get_room_for_player),
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    try:
        game.force_start_voting(db, room, player)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_room_state(room.code)
    return game.public_state(db, room, player)


@router.post("/{code}/force-close-vote")
async def force_close_vote(
    room: models.Room = Depends(get_room_for_player),
    player: models.Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    try:
        game.force_close_vote(db, room, player)
    except game.GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_room_state(room.code)
    return game.public_state(db, room, player)
