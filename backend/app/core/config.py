"""Validated configuration. Secrets have no insecure development defaults."""

from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_REVISION = "0001_foundation"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRADEORBIT_",
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )
    app_env: Literal["local", "test", "production"] = "local"
    database_url: SecretStr
    redis_url: SecretStr
    session_secret: SecretStr
    credential_encryption_key: SecretStr
    encryption_key_version: str = "v1"
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:18080",
        ]
    )
    cookie_secure: bool = False
    cookie_name: str = "tradeorbit_session"
    session_hours: int = Field(default=8, ge=1, le=24)
    login_attempts_per_minute: int = Field(default=8, ge=1, le=100)
    trading_enabled: bool = False

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if len(self.session_secret.get_secret_value()) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 characters")
        try:
            Fernet(self.credential_encryption_key.get_secret_value().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key") from exc
        if self.trading_enabled:
            raise ValueError("Trading is unavailable in the E01 foundation release")
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("Explicit allowed origins are required")
        if self.app_env == "production":
            if not self.cookie_secure:
                raise ValueError("Production requires secure cookies")
            if not all(origin.startswith("https://") for origin in self.allowed_origins):
                raise ValueError("Production requires HTTPS origins")
            if not self.database_url.get_secret_value().startswith("postgresql+asyncpg://"):
                raise ValueError("Production requires PostgreSQL")
        return self
