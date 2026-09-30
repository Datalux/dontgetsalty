from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import game
from ..db import get_db

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


@router.get("")
def get_suggestions(db: Session = Depends(get_db)):
    return game.public_suggestions(db)
