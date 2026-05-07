from __future__ import annotations

from pydantic import BaseModel, Field


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    is_admin: bool = False


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)

