from pydantic import BaseModel, Field


class CreateRoomRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=64)


class JoinRoomRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=64)


class StartRequest(BaseModel):
    rounds: int = Field(ge=1, le=20)


class QuestionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class VoteRequest(BaseModel):
    target_player_id: int


class SuggestionsRequest(BaseModel):
    enabled: bool
