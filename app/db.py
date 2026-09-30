from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

# In-memory only, by design: this build never writes game data to disk, so
# there is no .db file for anyone with server/filesystem access to open.
# The tradeoff is that a process restart loses all in-progress games — an
# accepted cost for a real anonymity guarantee (see README). StaticPool
# keeps a single persistent connection so every request shares the same
# in-memory database instead of each getting its own empty one.
SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    from . import models

    Base.metadata.create_all(bind=engine)
    _seed_suggestions_if_empty(models)


def _seed_suggestions_if_empty(models) -> None:
    from .suggestions_seed import SEED_SUGGESTIONS

    db = SessionLocal()
    try:
        if db.query(models.SuggestedQuestion).first() is not None:
            return
        for category, texts in SEED_SUGGESTIONS.items():
            for text in texts:
                db.add(models.SuggestedQuestion(category=category, text=text))
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
