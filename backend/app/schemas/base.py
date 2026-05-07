from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class APIMessage(BaseModel):
    message: str


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
