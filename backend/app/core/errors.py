"""Safe application errors and consistent response envelopes."""

from typing import Any

from fastapi import Request


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: Any = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def success(request: Request, data: Any, **meta: Any) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {"request_id": request.state.request_id, "schema_version": 1, **meta},
    }


def failure(request: Request, error: AppError) -> dict[str, Any]:
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "retryable": error.status in (429, 503),
            "details": error.details,
        },
        "meta": {"request_id": getattr(request.state, "request_id", None)},
    }
