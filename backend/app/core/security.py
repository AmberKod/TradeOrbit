"""Password hashing, opaque sessions, CSRF binding and authenticated encryption."""

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

PASSWORD_HASHER = PasswordHasher()
DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("Password length must be between 12 and 128 characters")
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        valid = PASSWORD_HASHER.verify(encoded or DUMMY_HASH, password)
        return bool(valid and encoded)
    except (VerificationError, InvalidHashError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token(token: str, signing_secret: str) -> str:
    return hmac.new(signing_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class CredentialCipher:
    def __init__(self, key: str, version: str):
        self._fernet = Fernet(key.encode("ascii"))
        self.version = version

    def encrypt(self, values: dict[str, str]) -> str:
        serialized = json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode()
        return self._fernet.encrypt(serialized).decode("ascii")

    def decrypt(self, ciphertext: str, version: str) -> dict[str, str]:
        if version != self.version:
            raise ValueError("Encryption key version is not available")
        result = json.loads(self._fernet.decrypt(ciphertext.encode("ascii")))
        if not isinstance(result, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in result.items()
        ):
            raise ValueError("Invalid credential payload")
        return result
