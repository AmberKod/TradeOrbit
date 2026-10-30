"""Strict input schemas; secret input is never used as output."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

Exchange = Literal["binance", "bitget", "okx"]
Environment = Literal["DEMO", "LIVE"]
AccountMode = Literal["STANDARD", "CLASSIC", "UTA", "UNIFIED", "UNKNOWN"]
MODES = {
    "binance": {"STANDARD", "UNKNOWN"},
    "bitget": {"CLASSIC", "UTA", "UNKNOWN"},
    "okx": {"UNIFIED", "UNKNOWN"},
}


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=80)
    exchange: Exchange
    environment: Environment = "DEMO"
    account_mode: AccountMode = "UNKNOWN"
    region_profile: str = Field(default="GLOBAL", pattern="^[A-Za-z0-9_-]{1,32}$")

    @model_validator(mode="after")
    def valid_mode(self) -> "AccountCreate":
        if self.account_mode not in MODES[self.exchange]:
            raise ValueError("Account mode does not match exchange")
        return self


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=80)


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = Field(min_length=1, max_length=2048)
    secret: SecretStr = Field(min_length=1, max_length=8192)
    passphrase: SecretStr | None = Field(default=None, max_length=2048)
