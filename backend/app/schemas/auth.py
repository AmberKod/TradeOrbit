"""Authentication inputs with bounded password length."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)
    workspace_id: UUID | None = None
