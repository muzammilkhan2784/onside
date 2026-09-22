"""Current football: real fixtures, tables and top scorers from
football-data.org, and the social feed around them.

Every answer comes from Redis, filled by the fixtures and social workers. The
API never calls an outside service on a user's request, so a slow or failing
feed can make the data stale but never makes a page slow.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Query

from ...social import store as social_store
from ...streams import bus
from ...workers import fixtures
from ..errors import ApiError

router = APIRouter(prefix="/api", tags=["current"])

TODAY_OFF = (
    "Current fixtures are switched off. Everything else on Onside is the StatsBomb "
    "open-data archive, which is history. Live fixtures come from football-data.org: "
    "set FOOTBALL_DATA_API_KEY (a free key from football-data.org) and restart the "
    "fixtures service."
)
STALE_S = 300


def _get(key: str) -> dict[str, Any] | None:
    raw = bus.sync_client().get(key)
    return json.loads(raw) if raw else None


def _fresh(body: dict[str, Any]) -> dict[str, Any]:
    body["stale"] = time.time() - float(body.get("fetchedAt") or 0) > STALE_S
    body["source"] = "football-data.org"
    return body


def _not_yet(what: str, code: str) -> ApiError:
    return ApiError(
        404,
        f"{what}_not_ready",
        f"The {what} for {code.upper()} has not been fetched yet. The fixtures service refreshes "
        "one competition a minute - try again shortly.",
        {"competition": code.upper()},
    )


@router.get("/today", summary="Real fixtures and results, three days back to sixteen ahead")
def today() -> dict[str, Any]:
    """Real matches - not replays - from football-data.org, refreshed every
    minute by the fixtures worker. `enabled` is false without an API key; the
    message then says how to switch it on. Free-tier scores can be delayed."""
    body = _get(fixtures.KEY)
    if not body:
        return {"enabled": False, "matches": [], "message": TODAY_OFF}
    if not body.get("enabled"):
        return {**body, "message": TODAY_OFF}
    return _fresh(body)


@router.get("/current/competitions", summary="Competitions with a season under way")
def current_competitions() -> list[dict[str, Any]]:
    """Each competition in the football-data.org plan whose current season is
    being played, with whether its table and scorers have been fetched yet."""
    body = _get(fixtures.COMPETITIONS) or {"data": []}
    live = set(fixtures.active(body["data"]))
    r = bus.sync_client()
    return [
        {
            **c,
            "hasTable": bool(r.exists(fixtures.standings_key(c["code"]))),
            "hasScorers": bool(r.exists(fixtures.scorers_key(c["code"]))),
        }
        for c in body["data"]
        if c["code"] in live
    ]


@router.get("/current/{code}/standings", summary="A competition's current table")
def current_standings(code: str) -> dict[str, Any]:
    """Tables refresh round-robin, one competition a minute; `fetchedAt` says
    how old this one is."""
    body = _get(fixtures.standings_key(code.upper()))
    if not body:
        raise _not_yet("table", code)
    return _fresh(body)


@router.get("/current/{code}/scorers", summary="A competition's current top scorers")
def current_scorers(code: str) -> dict[str, Any]:
    body = _get(fixtures.scorers_key(code.upper()))
    if not body:
        raise _not_yet("scorers", code)
    return _fresh(body)


# ---------------------------------------------------------------- social


@router.get("/social", summary="Public posts about football, newest first")
def social_feed(
    topic: str | None = Query(
        None, description="A fixture id (fd-...), a competition code, or 'all'"
    ),
    network: str | None = Query(None, description="bluesky, mastodon, reddit or x"),
    lang: str | None = Query(None, description="Two-letter language code, e.g. en"),
    before: float | None = Query(None, description="Cursor: only posts older than this"),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    """Public posts collected by the social worker, each with its author and a
    link to the original. Onside stores only what it shows and keeps it for
    three days."""
    items, nxt = social_store.page(
        bus.sync_client(), topic=topic, network=network, lang=lang, before=before, limit=limit
    )
    return {"items": items, "next": nxt}


@router.get("/social/overview", summary="Sources, trends and volume for the social dashboard")
def social_overview() -> dict[str, Any]:
    return social_store.overview(bus.sync_client())
