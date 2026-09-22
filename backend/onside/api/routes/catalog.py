"""The hub: home page, news feed, search, competitions, seasons and tables."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ...store import repo
from ...streams import bus
from .. import deps
from ..errors import not_found
from ..schemas import Competition, MatchCard, Page, SearchResult, Tables

router = APIRouter(prefix="/api", tags=["hub"])

FEED_TAGS = ("turnaround", "penalties", "goal-fest", "smash-and-grab", "stalemate", "knockout")


def _live_cards() -> list[dict[str, Any]]:
    """Replays that are actually playing right now. A replay that finished or
    was stopped keeps its document (so its page still works) but is no longer
    listed - a match from 2022 must never look like it is still going on."""
    try:
        playing = bus.playing_replays()
        return [c for c in repo.live_matches() if c.get("id") in playing]
    except Exception:  # noqa: BLE001 - the home page must render without live data
        return []


@router.get("/home", summary="Everything the front page needs in one request")
def home() -> dict[str, Any]:
    stats = deps.catalog("stats", "archive") or {}
    comps = deps.catalog("competitions") or []
    collections = deps.catalog("collections") or {}
    latest, _ = deps.cached("feed:latest", 60, lambda: repo.feed(limit=18))
    return {
        "archive": stats,
        "live": _live_cards(),
        "latest": latest,
        "collections": [
            {"id": k, **v, "matches": v["matches"][:8]} for k, v in collections.items()
        ],
        "competitions": [
            {k: c[k] for k in ("id", "name", "country", "gender", "international", "matches")}
            for c in comps
        ],
        "tags": list(FEED_TAGS),
    }


@router.get("/feed", response_model=Page[MatchCard], summary="The news feed")
def feed(
    tag: str | None = Query(None, description=f"One of {', '.join(FEED_TAGS)}"),
    cursor: str | None = None,
    limit: int = Query(24, ge=1, le=100),
) -> dict[str, Any]:
    """A story for every match in the archive, newest first. Each headline and
    standfirst is generated from the match's own win-probability swings."""
    items, nxt = repo.feed(limit=limit, cursor=cursor, tag=tag)
    return {"items": items, "next": nxt}


@router.get("/collections/{collection_id}", summary="One editorial collection in full")
def collection(collection_id: str) -> dict[str, Any]:
    cols = deps.catalog("collections") or {}
    if collection_id not in cols:
        raise not_found("collection", collection_id, f"Available: {', '.join(cols)}.")
    return {"id": collection_id, **cols[collection_id]}


@router.get("/live", response_model=list[MatchCard], summary="Matches replaying right now")
def live() -> list[dict[str, Any]]:
    return _live_cards()


@router.get(
    "/search", response_model=list[SearchResult], summary="Search competitions, teams and players"
)
def search(
    q: str = Query(..., min_length=2, max_length=60), limit: int = Query(20, ge=1, le=50)
) -> list[dict[str, Any]]:
    import unicodedata

    def fold(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
        ).lower()

    rows = deps.catalog("search") or []
    needle = fold(q.strip())
    hits = []
    for kind, ident, name, subtitle, weight in rows:
        n = fold(name)
        if needle not in n:
            continue
        # exact name, then a word that starts with the query, then anywhere -
        # and within a tier, whoever appears in the most matches.
        tier = 0 if n == needle else 1 if any(w.startswith(needle) for w in n.split()) else 2
        hits.append(
            ((tier, -weight), {"kind": kind, "id": ident, "name": name, "subtitle": subtitle})
        )
    hits.sort(key=lambda h: h[0])
    return [h[1] for h in hits[:limit]]


@router.get(
    "/competitions", response_model=list[Competition], summary="Every competition in the archive"
)
def competitions() -> list[dict[str, Any]]:
    return deps.catalog("competitions") or []


def _competition(cid: str) -> dict[str, Any]:
    for c in deps.catalog("competitions") or []:
        if c["id"] == cid:
            return c  # type: ignore[no-any-return]
    raise not_found("competition", cid, "GET /api/competitions lists them all.")


@router.get("/competitions/{competition_id}", response_model=Competition)
def competition(competition_id: str) -> dict[str, Any]:
    return _competition(competition_id)


@router.get("/competitions/{competition_id}/seasons")
def seasons(competition_id: str) -> list[dict[str, Any]]:
    return _competition(competition_id)["seasons"]  # type: ignore[no-any-return]


@router.get(
    "/competitions/{competition_id}/seasons/{season_id}/matches",
    response_model=list[MatchCard],
    summary="Every match in a competition-season",
)
def season_matches(competition_id: str, season_id: str) -> list[dict[str, Any]]:
    comp = _competition(competition_id)
    if not any(s["id"] == season_id for s in comp["seasons"]):
        raise not_found(
            "season",
            season_id,
            f"{comp['name']} has seasons {', '.join(s['name'] for s in comp['seasons'][:6])}.",
        )
    return deps.cached(
        f"cs:{competition_id}:{season_id}",
        300,
        lambda: repo.matches_for_competition_season(competition_id, season_id),
    )


@router.get(
    "/competitions/{competition_id}/table",
    response_model=Tables,
    summary="Standings, with the tie-break rule applied",
)
def table(competition_id: str, season: str = Query(..., description="Season id")) -> dict[str, Any]:
    """Tables are only built where the archive holds the full fixture list. When
    it does not - most La Liga seasons are Barcelona's matches only - `tables`
    is empty and `note` says why, rather than showing a table that is wrong."""
    _competition(competition_id)
    meta = deps.catalog("season", f"{competition_id}#{season}") or {}
    return {
        "competitionId": competition_id,
        "seasonId": season,
        "tables": repo.get_tables(competition_id, season),
        "note": meta.get("tablesNote", ""),
    }


@router.get("/archive", summary="How big the archive is")
def archive() -> dict[str, Any]:
    return deps.catalog("stats", "archive") or {}


@router.get("/entities/unresolved", summary="Cross-feed entities that could not be matched")
def unresolved() -> dict[str, Any]:
    """An honest accounting of what entity resolution could not match. Joining
    silently on a guess is worse than admitting it."""
    items = repo.unresolved_aliases()
    return {"count": len(items), "items": items}


def active_replay_ids() -> list[str]:
    return sorted(bus.sync_client().smembers(bus.ACTIVE_REPLAYS))
