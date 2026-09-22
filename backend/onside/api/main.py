"""The Onside API.

    uvicorn onside.api.main:app --reload

Public and read-only apart from replay control. `/docs` is part of the
product: it is the documented, free API over deep event data that the gap
analysis in the README says does not exist.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .. import __version__
from ..config import settings
from . import errors, lite, ws
from .metrics import METRICS
from .routes import catalog, current, entities, matches, ops
from .schemas import ErrorEnvelope

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

DESCRIPTION = """
**Correction-aware soccer match intelligence over every match in the StatsBomb open-data archive.**

* Every event with pitch coordinates, xG and 360 freeze-frames.
* A calibrated live win-probability model, and a match report generated from it.
* Corrections are first-class: a disallowed goal stays in the record with its reason,
  and `/score-at` answers what the score was at any moment.
* Replay any archived match live over WebSockets (`/ws/match/{id}?since=`).

Errors always look like `{"error": code, "message": "...", "detail": {}}`.
Event data: StatsBomb Open Data.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await ws.manager.start()
    yield
    await ws.manager.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Onside API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=[
            {
                "name": "hub",
                "description": "Home page, news feed, search, competitions and tables.",
            },
            {"name": "matches", "description": "Everything about one match."},
            {"name": "teams"},
            {"name": "players"},
            {"name": "analytics", "description": "DuckDB queries over the Parquet archive."},
            {"name": "replay", "description": "Replay any archived match live."},
            {"name": "lite", "description": "Server-rendered pages for slow connections."},
            {"name": "ops"},
        ],
        responses={
            404: {"model": ErrorEnvelope},
            422: {"model": ErrorEnvelope},
            500: {"model": ErrorEnvelope},
        },
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings().cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        t0 = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        route = getattr(request.scope.get("route"), "path", "unmatched")
        METRICS.observe(request.method, route, response.status_code, ms)
        response.headers["Server-Timing"] = f"app;dur={ms:.1f}"
        if (
            request.method == "GET"
            and response.status_code == 200
            and route.startswith("/api/")
            and "live" not in request.url.path
            and "replay" not in route
        ):
            response.headers.setdefault(
                "Cache-Control", "public, max-age=60, stale-while-revalidate=300"
            )
        return response

    errors.install(app)
    for r in (
        catalog.router,
        current.router,
        matches.router,
        entities.teams,
        entities.players,
        entities.analytics,
        ops.replay,
        ops.ops,
        lite.router,
        ws.router,
    ):
        app.include_router(r)
    return app


app = create_app()
