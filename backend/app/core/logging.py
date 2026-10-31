"""Structured metadata-only logs. Request bodies are never logged."""

import logging
from typing import Any

import structlog
from structlog.typing import EventDict

SENSITIVE = {
    "password",
    "secret",
    "api_key",
    "passphrase",
    "authorization",
    "cookie",
    "signature",
    "token",
    "ciphertext",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(part in str(key).lower() for part in SENSITIVE)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def redact_event(_logger: Any, _method: str, event: EventDict) -> EventDict:
    return redact(event)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # HTTPX INFO includes signed URLs; HTTP core debug may include request headers.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_event,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
