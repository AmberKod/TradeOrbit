"""Security primitives and configuration fail-closed behavior."""

import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import redact
from app.core.security import (
    CredentialCipher,
    csrf_token,
    hash_password,
    token_digest,
    verify_password,
)


def test_password_hash_and_csrf_are_bound_to_inputs():
    encoded = hash_password("Test-only-long-password")
    assert verify_password("Test-only-long-password", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("wrong", None)
    assert token_digest("raw-session") != "raw-session"
    assert csrf_token("first-session", "secret") != csrf_token("second-session", "secret")


def test_credential_cipher_rejects_tampering_and_wrong_key():
    key = Fernet.generate_key().decode()
    cipher = CredentialCipher(key, "v1")
    payload = {
        "api_key": "fixture-key",
        "secret": "fixture-secret",
        "passphrase": "fixture-passphrase",
    }
    encrypted = cipher.encrypt(payload)
    assert all(value not in encrypted for value in payload.values())
    assert cipher.decrypt(encrypted, "v1") == payload
    with pytest.raises(InvalidToken):
        CredentialCipher(Fernet.generate_key().decode(), "v1").decrypt(encrypted, "v1")
    with pytest.raises(ValueError):
        cipher.decrypt(encrypted, "unavailable-key-version")


def test_recursive_log_redaction():
    data = redact(
        {
            "password": "hidden",
            "nested": {"ACCESS-SIGNATURE": "hidden", "safe": "visible"},
            "items": [{"api_key": "hidden"}],
        }
    )
    assert "hidden" not in str(data)
    assert data["nested"]["safe"] == "visible"


def test_configuration_does_not_allow_accidental_trading():
    kwargs = dict(
        app_env="test",
        database_url="sqlite+aiosqlite://",
        redis_url="redis://localhost:1",
        session_secret="x" * 40,
        credential_encryption_key=Fernet.generate_key().decode(),
    )
    with pytest.raises(ValidationError):
        Settings(**kwargs, trading_enabled=True)
    with pytest.raises(ValidationError):
        Settings(**{**kwargs, "session_secret": "short-secret"})
    with pytest.raises(ValidationError):
        Settings(**{**kwargs, "app_env": "production", "cookie_secure": False})
