"""The error envelope.

Every error the API returns has the same shape:

    {"error": "match_not_found",
     "message": "There is no match 123 in the archive. ...",
     "detail": {...}}

`error` is a stable code for clients to branch on; `message` is written for a
human and says what happened and what to do. A raw exception or "Something went
wrong" never reaches a client - unexpected failures are logged with a request
id and the client gets that id to quote.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("onside.api")


class ApiError(Exception):
    def __init__(self, status: int, error: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message
        self.detail = detail or {}


def not_found(kind: str, ident: str, hint: str = "") -> ApiError:
    return ApiError(
        404,
        f"{kind}_not_found",
        f"There is no {kind} {ident!r} in the archive." + (f" {hint}" if hint else ""),
        {kind: ident},
    )


def unavailable(service: str, message: str) -> ApiError:
    return ApiError(503, f"{service}_unavailable", message, {"service": service})


def _envelope(
    status: int, error: str, message: str, detail: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": error, "message": message, "detail": detail or {}}
    )


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.status, exc.error, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            ".".join(str(p) for p in e["loc"] if p not in ("query", "path", "body"))
            for e in exc.errors()
        ]
        return _envelope(
            422,
            "invalid_request",
            f"Some parameters were not valid: {', '.join(f for f in fields if f)}. "
            "The API reference at /docs lists what each one accepts.",
            {
                "errors": [
                    {"field": f, "problem": e["msg"]}
                    for f, e in zip(fields, exc.errors(), strict=True)
                ]
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _envelope(
                404,
                "route_not_found",
                "That address is not part of the API. The reference at /docs lists every route.",
            )
        return _envelope(exc.status_code, "http_error", str(exc.detail))

    from ..archive.duck import ArchiveUnavailable

    @app.exception_handler(ArchiveUnavailable)
    async def _archive(_: Request, exc: ArchiveUnavailable) -> JSONResponse:
        log.error("analytics archive unavailable: %s", exc)
        return _envelope(
            503,
            "archive_unavailable",
            "The analytics archive is not reachable right now, so leaderboards and player "
            "seasons cannot be computed. Match pages are unaffected. Try again in a minute.",
            {"service": "archive"},
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        log.exception("unhandled error on %s %s [%s]", request.method, request.url.path, rid)
        return _envelope(
            500,
            "internal_error",
            f"The server hit a problem it did not expect while handling this request. "
            f"It has been logged; if it keeps happening, quote reference {rid}.",
            {"requestId": rid},
        )
