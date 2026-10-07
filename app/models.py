import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .db import Base


def utcnow() -> datetime:
    # Naive UTC on purpose: SQLite has no real timezone-aware storage, so a
    # tz-aware value written here comes back naive on the next read. Keeping
    # utcnow() itself naive means every value — freshly computed or read back
    # from the DB — is directly comparable (see game.py's grace-period checks).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_token() -> str:
    return uuid.uuid4().hex


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True)
    code = Column(String(8), unique=True, index=True, nullable=False)
    status = Column(String(32), nullable=False, default="lobby")
    total_rounds = Column(Integer, nullable=True)
    current_round = Column(Integer, nullable=False, default=0)
    suggestions_enabled = Column(Boolean, nullable=False, default=True)
    # Set once the host starts a fresh game for the same group of players —
    # points at a brand-new room rather than reusing/wiping this one, so a
    # finished game's questions and votes stay retrievable by its own code.
    next_room_code = Column(String(8), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    players = relationship(
        "Player", back_populates="room", cascade="all, delete-orphan"
    )
    rounds = relationship(
        "Round",
        back_populates="room",
        cascade="all, delete-orphan",
        order_by="Round.round_number",
    )


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    token = Column(String(32), unique=True, index=True, default=new_token)
    nickname = Column(String(64), nullable=False)
    is_host = Column(Boolean, nullable=False, default=False)
    connected = Column(Boolean, nullable=False, default=True)
    disconnected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    room = relationship("Room", back_populates="players")


class Round(Base):
    __tablename__ = "rounds"

    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    round_number = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="collecting_questions")

    room = relationship("Room", back_populates="rounds")
    questions = relationship(
        "Question",
        back_populates="round",
        cascade="all, delete-orphan",
        order_by="Question.order_index",
    )


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    round_id = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    author_player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    text = Column(String(500), nullable=False)
    order_index = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="pending")

    round = relationship("Round", back_populates="questions")
    author = relationship("Player", foreign_keys=[author_player_id])
    votes = relationship(
        "Vote", back_populates="question", cascade="all, delete-orphan"
    )


class SuggestedQuestion(Base):
    __tablename__ = "suggested_questions"

    id = Column(Integer, primary_key=True)
    category = Column(String(32), nullable=False, index=True)
    text = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("question_id", "voter_player_id", name="uq_one_vote_each"),
    )

    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    voter_player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    target_player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    question = relationship("Question", back_populates="votes")
    voter = relationship("Player", foreign_keys=[voter_player_id])
    target = relationship("Player", foreign_keys=[target_player_id])
