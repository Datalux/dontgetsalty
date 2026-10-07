import random
import string
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .config import MIN_PLAYERS, RECONNECT_GRACE_SECONDS
from .models import utcnow
from .suggestions_seed import CATEGORIES

CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1I")


class GameError(ValueError):
    """Raised for any invalid game action (bad phase, not host, etc.)."""


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def get_room_by_code(db: Session, code: str) -> models.Room | None:
    return db.query(models.Room).filter(models.Room.code == code.upper()).first()


def get_player_by_token(db: Session, token: str) -> models.Player | None:
    if not token:
        return None
    return db.query(models.Player).filter(models.Player.token == token).first()


def _current_round(room: models.Room) -> models.Round | None:
    for r in room.rounds:
        if r.round_number == room.current_round:
            return r
    return None


def _sorted_players(room: models.Room) -> list[models.Player]:
    return sorted(room.players, key=lambda p: p.id)


def _is_effectively_connected(player: models.Player) -> bool:
    """True if connected, or disconnected too recently to count as gone.

    A plain page refresh or a brief network blip triggers a disconnect/
    reconnect cycle; without this grace window that alone could shrink the
    "everyone has answered" threshold and close a question early.
    """
    if player.connected:
        return True
    if player.disconnected_at is None:
        return False
    return (utcnow() - player.disconnected_at) < timedelta(seconds=RECONNECT_GRACE_SECONDS)


def _effective_total(room: models.Room) -> int:
    count = sum(1 for p in room.players if _is_effectively_connected(p))
    return max(1, count)


def _can_act_as_host(room: models.Room, player: models.Player) -> bool:
    """True for the real host, or for anyone when the host is gone.

    "Gone" uses the same grace window as everything else, so a host who
    merely refreshed their page doesn't briefly lose control to someone else.
    """
    if player.is_host:
        return True
    host = next((p for p in room.players if p.is_host), None)
    return host is None or not _is_effectively_connected(host)


# --------------------------------------------------------------------------
# Lobby: create / join / start
# --------------------------------------------------------------------------

def _generate_room_code(db: Session) -> str:
    for _ in range(50):
        code = "".join(random.choices(CODE_ALPHABET, k=5))
        if not get_room_by_code(db, code):
            return code
    raise GameError("Impossibile generare un codice stanza univoco, riprova.")


def create_room(db: Session, nickname: str) -> tuple[models.Room, models.Player]:
    room = models.Room(code=_generate_room_code(db), status="lobby")
    db.add(room)
    db.flush()

    player = models.Player(room_id=room.id, nickname=nickname.strip(), is_host=True)
    db.add(player)
    db.commit()
    db.refresh(room)
    db.refresh(player)
    return room, player


def join_room(db: Session, code: str, nickname: str) -> tuple[models.Room, models.Player]:
    room = get_room_by_code(db, code)
    if room is None:
        raise GameError("Codice stanza non valido.")
    if room.status != "lobby":
        raise GameError("La partita e' gia' iniziata, non e' piu' possibile entrare.")

    nickname = nickname.strip()
    existing_names = {p.nickname.lower() for p in room.players}
    if nickname.lower() in existing_names:
        raise GameError("Questo nickname e' gia' in uso nella stanza.")

    player = models.Player(room_id=room.id, nickname=nickname, is_host=False)
    db.add(player)
    db.commit()
    db.refresh(room)
    db.refresh(player)
    return room, player


def start_game(db: Session, room: models.Room, player: models.Player, rounds: int) -> None:
    if not _can_act_as_host(room, player):
        raise GameError("Solo l'host puo' avviare la partita.")
    if room.status != "lobby":
        raise GameError("La partita e' gia' stata avviata.")
    if len(room.players) < MIN_PLAYERS:
        raise GameError(f"Servono almeno {MIN_PLAYERS} giocatori per iniziare.")

    room.total_rounds = rounds
    room.current_round = 1
    room.status = "collecting_questions"
    db.add(models.Round(room_id=room.id, round_number=1, status="collecting_questions"))
    db.commit()


def start_new_room_from(db: Session, room: models.Room, player: models.Player) -> models.Player:
    """Replay with the same group: open a brand-new room (fresh code) with
    the acting host already seated in it (they're arriving right now, as
    part of this very action), for it to join into — this room's questions
    and votes stay exactly as they are, still retrievable by its own code,
    never overwritten by the next game. Deliberately doesn't pre-seat anyone
    else there: every other player only shows up in the new room's lobby
    once they actually join it themselves, same as any other room — not the
    moment the host starts it."""
    if not _can_act_as_host(room, player):
        raise GameError("Solo l'host puo' avviare una nuova partita.")
    if room.status != "finished":
        raise GameError("La partita non e' ancora conclusa.")
    if room.next_room_code:
        raise GameError("E' gia' stata avviata una nuova partita per questo gruppo.")

    new_room = models.Room(code=_generate_room_code(db), status="lobby")
    db.add(new_room)
    db.flush()

    new_host = models.Player(room_id=new_room.id, nickname=player.nickname, is_host=True)
    db.add(new_host)
    room.next_room_code = new_room.code
    db.commit()
    db.refresh(new_host)
    return new_host


def remove_player(db: Session, room: models.Room, player: models.Player, target_id: int) -> None:
    if not _can_act_as_host(room, player):
        raise GameError("Solo l'host puo' rimuovere un giocatore.")
    if room.status != "lobby":
        raise GameError("Puoi rimuovere giocatori solo prima di avviare la partita.")
    target = next((p for p in room.players if p.id == target_id), None)
    if target is None:
        raise GameError("Giocatore non trovato.")
    if target.is_host or target.id == player.id:
        raise GameError("Non puoi rimuovere l'host o te stesso.")

    db.delete(target)
    db.commit()


def set_suggestions_enabled(db: Session, room: models.Room, player: models.Player, enabled: bool) -> None:
    if not _can_act_as_host(room, player):
        raise GameError("Solo l'host puo' cambiare questa impostazione.")
    if room.status != "lobby":
        raise GameError("Puoi cambiare questa impostazione solo prima di avviare la partita.")

    room.suggestions_enabled = enabled
    db.commit()


# --------------------------------------------------------------------------
# Round: question submission
# --------------------------------------------------------------------------

def submit_question(db: Session, room: models.Room, player: models.Player, text: str) -> None:
    if room.status != "collecting_questions":
        raise GameError("Non e' il momento di proporre domande.")

    round_ = _current_round(room)
    if round_ is None or round_.status != "collecting_questions":
        raise GameError("Non e' il momento di proporre domande.")

    text = text.strip()
    if not text:
        raise GameError("La domanda non puo' essere vuota.")

    existing = (
        db.query(models.Question)
        .filter(
            models.Question.round_id == round_.id,
            models.Question.author_player_id == player.id,
        )
        .first()
    )
    if existing is not None:
        existing.text = text
    else:
        db.add(
            models.Question(
                round_id=round_.id,
                author_player_id=player.id,
                text=text,
                status="pending",
            )
        )
    db.commit()

    _maybe_start_voting(db, room, round_)


def _maybe_start_voting(db: Session, room: models.Room, round_: models.Round) -> None:
    db.refresh(round_)
    submitted = len(round_.questions)
    total = _effective_total(room)
    if submitted < total:
        return
    _start_voting(db, room, round_)


def _start_voting(db: Session, room: models.Room, round_: models.Round) -> None:
    questions = list(round_.questions)
    random.shuffle(questions)
    for index, question in enumerate(questions):
        question.order_index = index
    questions[0].status = "active"
    round_.status = "voting"
    room.status = "voting"
    db.commit()


def force_start_voting(db: Session, room: models.Room, player: models.Player) -> None:
    if not _can_act_as_host(room, player):
        raise GameError("Solo l'host puo' forzare l'inizio della votazione.")
    if room.status != "collecting_questions":
        raise GameError("Non e' il momento di forzare la votazione.")

    round_ = _current_round(room)
    if round_ is None:
        raise GameError("Round non trovato.")
    db.refresh(round_)
    if not round_.questions:
        raise GameError("Nessuna domanda e' ancora stata inviata.")

    _start_voting(db, room, round_)


# --------------------------------------------------------------------------
# Round: voting
# --------------------------------------------------------------------------

def _active_question(round_: models.Round) -> models.Question | None:
    for q in sorted(round_.questions, key=lambda q: q.order_index or 0):
        if q.status == "active":
            return q
    return None


def submit_vote(db: Session, room: models.Room, player: models.Player, target_player_id: int) -> None:
    if room.status != "voting":
        raise GameError("Non e' il momento di votare.")

    round_ = _current_round(room)
    question = _active_question(round_) if round_ else None
    if question is None:
        raise GameError("Nessuna domanda attiva al momento.")

    target_ids = {p.id for p in room.players}
    if target_player_id not in target_ids:
        raise GameError("Giocatore non valido.")

    vote = models.Vote(
        question_id=question.id,
        voter_player_id=player.id,
        target_player_id=target_player_id,
    )
    db.add(vote)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise GameError("Hai gia' votato per questa domanda.")

    _maybe_close_question(db, room, question)


def _maybe_close_question(db: Session, room: models.Room, question: models.Question) -> None:
    db.refresh(question)
    votes_cast = len(question.votes)
    votes_total = _effective_total(room)
    if votes_cast >= votes_total:
        question.status = "done"
        db.commit()


def force_close_vote(db: Session, room: models.Room, player: models.Player) -> None:
    if not _can_act_as_host(room, player):
        raise GameError("Solo l'host puo' forzare la chiusura del voto.")
    if room.status != "voting":
        raise GameError("Non c'e' una votazione in corso.")

    round_ = _current_round(room)
    question = _active_question(round_) if round_ else None
    if question is None:
        raise GameError("Nessuna domanda attiva al momento.")

    question.status = "done"
    db.commit()


def advance(db: Session, room: models.Room, player: models.Player) -> None:
    if not _can_act_as_host(room, player):
        raise GameError("Solo l'host puo' avanzare alla domanda successiva.")
    if room.status != "voting":
        raise GameError("Non c'e' nulla da avanzare ora.")

    round_ = _current_round(room)
    if round_ is None:
        raise GameError("Round non trovato.")

    current = _active_question(round_)
    if current is not None:
        if current.status != "done":
            raise GameError("La domanda attuale non ha ancora tutti i voti.")

    ordered = sorted(round_.questions, key=lambda q: q.order_index or 0)
    pending = [q for q in ordered if q.status == "pending"]

    if pending:
        pending[0].status = "active"
        db.commit()
        return

    round_.status = "done"

    if room.current_round < (room.total_rounds or 0):
        room.current_round += 1
        room.status = "collecting_questions"
        db.add(
            models.Round(
                room_id=room.id,
                round_number=room.current_round,
                status="collecting_questions",
            )
        )
    else:
        room.status = "finished"

    db.commit()


# --------------------------------------------------------------------------
# Public (anonymised) state, for players
# --------------------------------------------------------------------------

def public_state(db: Session, room: models.Room, player: models.Player) -> dict:
    db.refresh(room)
    players = _sorted_players(room)

    state: dict = {
        "room_code": room.code,
        "status": room.status,
        "is_host": player.is_host,
        "can_act_as_host": _can_act_as_host(room, player),
        "you": {"id": player.id, "nickname": player.nickname},
        "players": [
            {
                "id": p.id,
                "nickname": p.nickname,
                "connected": p.connected,
                "is_host": p.is_host,
            }
            for p in players
        ],
        "min_players": MIN_PLAYERS,
        "suggestions_enabled": room.suggestions_enabled,
    }

    if room.status == "lobby":
        state["can_start"] = len(players) >= MIN_PLAYERS
        return state

    state["current_round"] = room.current_round
    state["total_rounds"] = room.total_rounds

    round_ = _current_round(room)

    if room.status == "collecting_questions" and round_ is not None:
        my_question = next(
            (q for q in round_.questions if q.author_player_id == player.id), None
        )
        state["questions_submitted"] = len(round_.questions)
        state["questions_total"] = len(players)
        state["you_submitted"] = my_question is not None
        state["your_question_text"] = my_question.text if my_question else None
        return state

    if room.status == "voting" and round_ is not None:
        ordered = sorted(round_.questions, key=lambda q: q.order_index or 0)
        state["question_count"] = len(ordered)

        # Questions resolve strictly in order: a prefix is "done", then at most
        # one "active", then a suffix of "pending". The one players should see
        # right now is the last non-pending one (in-progress, or just closed
        # and awaiting the host's "next" action).
        non_pending = [q for q in ordered if q.status != "pending"]
        current = non_pending[-1] if non_pending else None

        if current is not None:
            state["question_index"] = (current.order_index or 0) + 1
            state["question"] = {"text": current.text}
            your_vote = next(
                (v for v in current.votes if v.voter_player_id == player.id), None
            )
            state["you_voted"] = your_vote is not None
            state["you_vote_target"] = your_vote.target_player_id if your_vote else None
            state["votes_cast"] = len(current.votes)
            state["votes_total"] = len(players)
            state["question_done"] = current.status == "done"
            if current.status == "done":
                state["tally"] = _tally(current, players)
            state["round_complete"] = current.status == "done" and len(non_pending) == len(ordered)
            state["has_next_round"] = room.current_round < (room.total_rounds or 0)

        return state

    if room.status == "finished":
        state["recap"] = _full_recap(room)
        leaderboard, scored_questions = _guess_leaderboard(room, players)
        state["guess_leaderboard"] = leaderboard
        state["guess_questions_total"] = scored_questions
        if room.next_room_code:
            state["next_room_code"] = room.next_room_code
        return state

    return state


def _tally(question: models.Question, players: list[models.Player]) -> list[dict]:
    counts: dict[int, int] = {p.id: 0 for p in players}
    for vote in question.votes:
        counts[vote.target_player_id] = counts.get(vote.target_player_id, 0) + 1
    by_nickname = {p.id: p.nickname for p in players}
    result = [
        {"player_id": pid, "nickname": by_nickname.get(pid, "?"), "votes": count}
        for pid, count in counts.items()
    ]
    result.sort(key=lambda r: (-r["votes"], r["nickname"].lower()))
    return result


def _guess_leaderboard(room: models.Room, players: list[models.Player]) -> tuple[list[dict], int]:
    """Score players on how often their vote matched the group's plurality
    choice for a question — "who reads the room best" — rather than on how
    many votes they personally received (which favours no one in particular,
    since categories range from flattering to embarrassing).
    """
    scores: dict[int, int] = {p.id: 0 for p in players}
    scored_questions = 0

    for round_ in room.rounds:
        for q in round_.questions:
            if q.status != "done" or not q.votes:
                continue
            counts: dict[int, int] = {}
            for vote in q.votes:
                counts[vote.target_player_id] = counts.get(vote.target_player_id, 0) + 1
            top_votes = max(counts.values())
            leaders = {pid for pid, c in counts.items() if c == top_votes}
            scored_questions += 1
            for vote in q.votes:
                if vote.target_player_id in leaders:
                    scores[vote.voter_player_id] = scores.get(vote.voter_player_id, 0) + 1

    by_nickname = {p.id: p.nickname for p in players}
    result = [
        {"player_id": pid, "nickname": by_nickname.get(pid, "?"), "score": score}
        for pid, score in scores.items()
    ]
    result.sort(key=lambda r: (-r["score"], r["nickname"].lower()))
    return result, scored_questions


def _full_recap(room: models.Room) -> list[dict]:
    players = _sorted_players(room)
    recap = []
    for round_ in sorted(room.rounds, key=lambda r: r.round_number):
        questions = []
        for q in sorted(round_.questions, key=lambda q: q.order_index or 0):
            questions.append({"text": q.text, "tally": _tally(q, players)})
        recap.append({"round_number": round_.round_number, "questions": questions})
    return recap


# --------------------------------------------------------------------------
# Suggested questions bank
# --------------------------------------------------------------------------

def public_suggestions(db: Session) -> dict[str, list[str]]:
    rows = db.query(models.SuggestedQuestion).order_by(models.SuggestedQuestion.id).all()
    grouped: dict[str, list[str]] = {c: [] for c in CATEGORIES}
    for row in rows:
        grouped.setdefault(row.category, []).append(row.text)
    return grouped


def room_suggestions(db: Session, room: models.Room) -> dict[str, list[str]]:
    """The suggestion bank, minus any suggestion already submitted verbatim
    as a question somewhere in this room — so the same "Chi arriva sempre in
    ritardo?" doesn't get offered to a second player after someone already
    sent it, in this round or an earlier one. A suggestion edited after being
    picked no longer matches exactly, so it's treated as a new question and
    doesn't block the original from being suggested again.
    """
    used = {q.text for round_ in room.rounds for q in round_.questions}
    grouped = public_suggestions(db)
    return {category: [t for t in texts if t not in used] for category, texts in grouped.items()}
