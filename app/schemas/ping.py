from pydantic import BaseModel, Field

DEFAULT_PING_MESSAGE = "Hello!"


class Ping(BaseModel):
    message: str = Field(DEFAULT_PING_MESSAGE, description="Ping message")
