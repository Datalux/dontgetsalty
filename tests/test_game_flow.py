import json
import os
from datetime import timedelta

os.environ["GGAME_MIN_PLAYERS"] = "3"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def mark_disconnected(player_id: int, seconds_ago: float) -> None:
    """Directly set a player's connection state, as the WS endpoint would
    after a disconnect — bypassing the real WebSocket (whose disconnect
    handler runs as a background task with no synchronous completion point
    to await from a test) so the resulting state is deterministic."""
    from app.db import SessionLocal
    from app import models

    db = SessionLocal()
    try:
        player = db.get(models.Player, player_id)
        player.connected = False
        player.disconnected_at = models.utcnow() - timedelta(seconds=seconds_ago)
        db.commit()
    finally:
        db.close()


def test_full_game_flow_stays_anonymous(client: TestClient):
    r = client.post("/api/rooms", json={"nickname": "Host"})
    assert r.status_code == 200
    room = r.json()
    code = room["room_code"]
    host_token = room["player_token"]

    players = [{"nickname": "Host", "token": host_token, "id": room["player_id"]}]
    for name in ["Ada", "Bea"]:
        r = client.post(f"/api/rooms/{code}/join", json={"nickname": name})
        assert r.status_code == 200
        data = r.json()
        players.append({"nickname": name, "token": data["player_token"], "id": data["player_id"]})

    state = client.get(f"/api/rooms/{code}/state", headers=auth(host_token)).json()
    assert state["status"] == "lobby"
    assert state["can_start"] is True
    assert len(state["players"]) == 3

    r = client.post(f"/api/rooms/{code}/start", json={"rounds": 1}, headers=auth(host_token))
    assert r.status_code == 200
    assert r.json()["status"] == "collecting_questions"

    for p in players:
        r = client.post(
            f"/api/rooms/{code}/questions",
            json={"text": f"Domanda di {p['nickname']}"},
            headers=auth(p["token"]),
        )
        assert r.status_code == 200

    state = client.get(f"/api/rooms/{code}/state", headers=auth(host_token)).json()
    assert state["status"] == "voting"
    assert state["question_count"] == 3
    assert "author" not in json.dumps(state).lower()

    for question_num in range(3):
        state = client.get(f"/api/rooms/{code}/state", headers=auth(host_token)).json()
        assert state["question"] is not None

        for p in players:
            r = client.post(
                f"/api/rooms/{code}/votes",
                json={"target_player_id": players[0]["id"]},
                headers=auth(p["token"]),
            )
            assert r.status_code == 200

        state = client.get(f"/api/rooms/{code}/state", headers=auth(host_token)).json()
        assert state["question_done"] is True
        assert sum(t["votes"] for t in state["tally"]) == 3
        assert "author" not in json.dumps(state).lower()
        assert "voter" not in json.dumps(state).lower()

        r = client.post(f"/api/rooms/{code}/advance", headers=auth(host_token))
        assert r.status_code == 200

    final_state = client.get(f"/api/rooms/{code}/state", headers=auth(host_token)).json()
    assert final_state["status"] == "finished"
    assert len(final_state["recap"]) == 1
    assert len(final_state["recap"][0]["questions"]) == 3
    assert "author" not in json.dumps(final_state).lower()


def test_cannot_start_below_min_players(client: TestClient):
    r = client.post("/api/rooms", json={"nickname": "Solo"})
    room = r.json()
    r = client.post(
        f"/api/rooms/{room['room_code']}/start",
        json={"rounds": 1},
        headers=auth(room["player_token"]),
    )
    assert r.status_code == 400


def test_suggestions_toggle_is_host_only_and_lobby_only(client: TestClient):
    r = client.post("/api/rooms", json={"nickname": "Host"})
    room = r.json()
    code, host_token = room["room_code"], room["player_token"]

    r = client.post(f"/api/rooms/{code}/join", json={"nickname": "Guest"})
    guest_token = r.json()["player_token"]

    state = client.get(f"/api/rooms/{code}/state", headers=auth(host_token)).json()
    assert state["suggestions_enabled"] is True

    r = client.post(
        f"/api/rooms/{code}/suggestions", json={"enabled": False}, headers=auth(guest_token)
    )
    assert r.status_code == 400

    r = client.post(
        f"/api/rooms/{code}/suggestions", json={"enabled": False}, headers=auth(host_token)
    )
    assert r.status_code == 200
    assert r.json()["suggestions_enabled"] is False

    client.post(f"/api/rooms/{code}/join", json={"nickname": "Third"})
    client.post(f"/api/rooms/{code}/start", json={"rounds": 1}, headers=auth(host_token))

    r = client.post(
        f"/api/rooms/{code}/suggestions", json={"enabled": True}, headers=auth(host_token)
    )
    assert r.status_code == 400


def test_suggestions_bank_is_seeded(client: TestClient):
    r = client.get("/api/suggestions")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"semplice", "piccante", "esplicito"}
    assert len(data["semplice"]) > 0
    assert len(data["piccante"]) > 0
    assert len(data["esplicito"]) > 0


def _setup_three_player_room(client: TestClient):
    r = client.post("/api/rooms", json={"nickname": "Host"})
    room = r.json()
    code, host_token, host_id = room["room_code"], room["player_token"], room["player_id"]

    r = client.post(f"/api/rooms/{code}/join", json={"nickname": "Ada"})
    ada = r.json()
    r = client.post(f"/api/rooms/{code}/join", json={"nickname": "Bea"})
    bea = r.json()

    client.post(f"/api/rooms/{code}/start", json={"rounds": 1}, headers=auth(host_token))
    return {
        "code": code,
        "host_token": host_token,
        "host_id": host_id,
        "ada_token": ada["player_token"],
        "ada_id": ada["player_id"],
        "bea_token": bea["player_token"],
        "bea_id": bea["player_id"],
    }


def test_room_suggestions_exclude_already_submitted(client: TestClient):
    room = _setup_three_player_room(client)
    code = room["code"]

    bank = client.get("/api/suggestions").json()
    picked = bank["semplice"][0]

    r = client.get(f"/api/rooms/{code}/suggestions", headers=auth(room["host_token"]))
    assert picked in r.json()["semplice"]

    client.post(f"/api/rooms/{code}/questions", json={"text": picked}, headers=auth(room["host_token"]))

    r = client.get(f"/api/rooms/{code}/suggestions", headers=auth(room["ada_token"]))
    assert picked not in r.json()["semplice"]

    # a different, not-yet-submitted suggestion stays available to everyone else
    r = client.get(f"/api/rooms/{code}/suggestions", headers=auth(room["bea_token"]))
    other = next(t for t in bank["semplice"] if t != picked)
    assert other in r.json()["semplice"]


def test_grace_period_protects_a_brief_disconnect(client: TestClient):
    room = _setup_three_player_room(client)
    code = room["code"]

    # Bea just disconnected (e.g. a page refresh) — she should still count
    # toward the threshold while inside the grace window.
    mark_disconnected(room["bea_id"], seconds_ago=1)

    client.post(f"/api/rooms/{code}/questions", json={"text": "Q1?"}, headers=auth(room["host_token"]))
    r = client.post(f"/api/rooms/{code}/questions", json={"text": "Q2?"}, headers=auth(room["ada_token"]))
    assert r.json()["status"] == "collecting_questions"
    assert r.json()["questions_submitted"] == 2
    assert r.json()["questions_total"] == 3


def test_expired_disconnect_no_longer_blocks_progress(client: TestClient):
    room = _setup_three_player_room(client)
    code = room["code"]

    mark_disconnected(room["bea_id"], seconds_ago=3600)

    client.post(f"/api/rooms/{code}/questions", json={"text": "Q1?"}, headers=auth(room["host_token"]))
    r = client.post(f"/api/rooms/{code}/questions", json={"text": "Q2?"}, headers=auth(room["ada_token"]))
    assert r.json()["status"] == "voting"

    # Voting should likewise close with just the two of them once Bea's gone.
    r = client.post(f"/api/rooms/{code}/votes", json={"target_player_id": room["host_id"]}, headers=auth(room["host_token"]))
    assert r.json()["question_done"] is False
    r = client.post(f"/api/rooms/{code}/votes", json={"target_player_id": room["host_id"]}, headers=auth(room["ada_token"]))
    assert r.json()["question_done"] is True


def test_host_fallback_when_host_is_gone(client: TestClient):
    room = _setup_three_player_room(client)
    code = room["code"]

    for token in (room["host_token"], room["ada_token"], room["bea_token"]):
        r = client.post(f"/api/rooms/{code}/questions", json={"text": "Q?"}, headers=auth(token))
    assert r.json()["status"] == "voting"  # all 3 submitted while everyone still looked connected

    # Now the host goes away long enough for the grace window to expire.
    mark_disconnected(room["host_id"], seconds_ago=3600)

    # advance (and force-close-vote) are host-only, but the host is gone —
    # Ada should be able to act on their behalf for all 3 questions.
    for _ in range(3):
        r = client.post(f"/api/rooms/{code}/force-close-vote", headers=auth(room["ada_token"]))
        assert r.status_code == 200, r.text
        r = client.post(f"/api/rooms/{code}/advance", headers=auth(room["ada_token"]))
        assert r.status_code == 200, r.text
    assert r.json()["status"] == "finished"


def test_force_start_voting_and_force_close_vote(client: TestClient):
    room = _setup_three_player_room(client)
    code = room["code"]

    # Can't force voting with zero questions submitted yet.
    r = client.post(f"/api/rooms/{code}/force-start-voting", headers=auth(room["host_token"]))
    assert r.status_code == 400

    client.post(f"/api/rooms/{code}/questions", json={"text": "Q1?"}, headers=auth(room["host_token"]))

    # A regular (connected, present) host player can't be overridden by someone else.
    r = client.post(f"/api/rooms/{code}/force-start-voting", headers=auth(room["ada_token"]))
    assert r.status_code == 400

    r = client.post(f"/api/rooms/{code}/force-start-voting", headers=auth(room["host_token"]))
    assert r.status_code == 200
    assert r.json()["status"] == "voting"
    assert r.json()["votes_total"] == 3

    # Nothing to force-close before anyone has voted is still valid — closes with 0 votes.
    r = client.post(f"/api/rooms/{code}/votes", json={"target_player_id": room["ada_id"]}, headers=auth(room["ada_token"]))
    assert r.json()["question_done"] is False

    r = client.post(f"/api/rooms/{code}/force-close-vote", headers=auth(room["host_token"]))
    assert r.status_code == 200
    assert r.json()["question_done"] is True
    assert sum(t["votes"] for t in r.json()["tally"]) == 1

    # And now there's nothing active left to force-close.
    r = client.post(f"/api/rooms/{code}/force-close-vote", headers=auth(room["host_token"]))
    assert r.status_code == 400


def test_guess_leaderboard_rewards_matching_the_plurality(client: TestClient):
    room = _setup_three_player_room(client)
    code = room["code"]
    host_id, ada_id, bea_id = room["host_id"], room["ada_id"], room["bea_id"]

    for token in (room["host_token"], room["ada_token"], room["bea_token"]):
        client.post(f"/api/rooms/{code}/questions", json={"text": "Q?"}, headers=auth(token))

    # On every question: Host and Bea both vote for Ada (the plurality winner,
    # 2 votes), Ada votes for Bea (not the winner) — so Host and Bea should
    # score a point each question, Ada should score none.
    r = None
    for _ in range(3):
        client.post(f"/api/rooms/{code}/votes", json={"target_player_id": ada_id}, headers=auth(room["host_token"]))
        client.post(f"/api/rooms/{code}/votes", json={"target_player_id": bea_id}, headers=auth(room["ada_token"]))
        r = client.post(f"/api/rooms/{code}/votes", json={"target_player_id": ada_id}, headers=auth(room["bea_token"]))
        assert r.json()["question_done"] is True
        r = client.post(f"/api/rooms/{code}/advance", headers=auth(room["host_token"]))

    assert r.json()["status"] == "finished"
    assert r.json()["guess_questions_total"] == 3
    board = {row["player_id"]: row["score"] for row in r.json()["guess_leaderboard"]}
    assert board[host_id] == 3
    assert board[bea_id] == 3
    assert board[ada_id] == 0
    assert "voter" not in json.dumps(r.json()).lower()
    assert "author" not in json.dumps(r.json()).lower()


def _play_to_finished(client: TestClient, room: dict) -> None:
    code = room["code"]
    for tok in (room["host_token"], room["ada_token"], room["bea_token"]):
        client.post(f"/api/rooms/{code}/questions", json={"text": "Q?"}, headers=auth(tok))
    for _ in range(3):
        for tok in (room["host_token"], room["ada_token"], room["bea_token"]):
            client.post(
                f"/api/rooms/{code}/votes", json={"target_player_id": room["host_id"]}, headers=auth(tok)
            )
        client.post(f"/api/rooms/{code}/advance", headers=auth(room["host_token"]))


def test_new_room_keeps_old_room_intact_and_moves_group_to_a_fresh_code(client: TestClient):
    room = _setup_three_player_room(client)
    code = room["code"]
    _play_to_finished(client, room)

    old_state = client.get(f"/api/rooms/{code}/state", headers=auth(room["host_token"])).json()
    assert old_state["status"] == "finished"
    old_recap = old_state["recap"]

    # non-host can't start a new room
    r = client.post(f"/api/rooms/{code}/new-room", headers=auth(room["ada_token"]))
    assert r.status_code == 400

    r = client.post(f"/api/rooms/{code}/new-room", headers=auth(room["host_token"]))
    assert r.status_code == 200
    new_code = r.json()["next_room_code"]
    assert new_code != code
    host_seat = r.json()["your_new_room"]
    assert host_seat["code"] == new_code

    # only one successor room per finished game
    r = client.post(f"/api/rooms/{code}/new-room", headers=auth(room["host_token"]))
    assert r.status_code == 400

    # the old room is completely untouched: same status, same recap, still
    # reachable by its own code — this is the whole point of not reusing it
    still_old_state = client.get(f"/api/rooms/{code}/state", headers=auth(room["host_token"])).json()
    assert still_old_state["status"] == "finished"
    assert still_old_state["recap"] == old_recap

    # everyone learns the new room's code, but nobody except the host (who
    # just arrived, as part of creating it) is pre-seated there
    ada_state = client.get(f"/api/rooms/{code}/state", headers=auth(room["ada_token"])).json()
    assert ada_state["next_room_code"] == new_code
    assert "your_new_room" not in ada_state

    lobby_host_only = client.get(f"/api/rooms/{new_code}/state", headers=auth(host_seat["player_token"])).json()
    assert lobby_host_only["status"] == "lobby"
    assert [p["nickname"] for p in lobby_host_only["players"]] == ["Host"]

    # Ada and Bea only show up once they actually join it themselves
    r = client.post(f"/api/rooms/{new_code}/join", json={"nickname": "Ada"})
    assert r.status_code == 200
    ada_token = r.json()["player_token"]
    r = client.post(f"/api/rooms/{new_code}/join", json={"nickname": "Bea"})
    assert r.status_code == 200

    new_lobby = client.get(f"/api/rooms/{new_code}/state", headers=auth(ada_token)).json()
    assert {p["nickname"] for p in new_lobby["players"]} == {"Host", "Ada", "Bea"}

    r = client.post(f"/api/rooms/{new_code}/start", json={"rounds": 1}, headers=auth(host_seat["player_token"]))
    assert r.status_code == 200
    assert r.json()["status"] == "collecting_questions"
    assert r.json()["current_round"] == 1
