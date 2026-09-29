from pydantic import BaseModel, Field, field_validator


class UserIn(BaseModel):
    name: str | None = None
    date_of_birth: str | None = None
    time_of_birth: str | None = None
    birth_place: str | None = None
    language: str | None = None


class UserOut(UserIn):
    id: str
    sun_sign: str | None = None
    created_at: str
    updated_at: str


class SessionIn(BaseModel):
    user_id: str = Field(min_length=1)


class SessionOut(BaseModel):
    id: str
    user_id: str
    created_at: str


class ChatIn(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str | None = None
    message: str

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("message is required")
        return cleaned

    @field_validator("session_id")
    @classmethod
    def blank_session_means_new(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ChatOut(BaseModel):
    response: str
    user_id: str
    session_id: str
    context_used: list[str]


class MessageOut(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    created_at: str


class MemoryOut(BaseModel):
    id: int
    kind: str
    relation: str
    label: str
    attributes: dict
    status: str
    confidence: float
