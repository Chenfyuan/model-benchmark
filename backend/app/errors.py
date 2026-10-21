from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: list[str] | None = None):
        self.code, self.message, self.status, self.details = code, message, status, details


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handler(_: Request, exc: ApiError):
        body = {"code": exc.code, "message": exc.message}
        if exc.details:
            body["details"] = exc.details
        return JSONResponse(status_code=exc.status, content=body)
