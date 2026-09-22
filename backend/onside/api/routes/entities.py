"""Teams, players and analytics."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query

from ...archive import queries
from ...store import repo
from .. import deps
from ..errors import ApiError, not_found
from ..schemas import Leaderboard, MatchCard, Page

teams = APIRouter(prefix="/api/teams", tags=["teams"])
players = APIRouter(prefix="/api/players", tags=["players"])
analytics = APIRouter(prefix="/api/analytics", tags=["analytics"])


@teams.get("/{team_id}", summary="A team's record across the archive")
def team(team_id: str) -> dict[str, Any]:
    t = repo.get_entity("team", team_id)
    if t is None:
        raise not_found("team", team_id)
    return t


@teams.get(
    "/{team_id}/matches", response_model=Page[MatchCard], summary="A team's matches, newest first"
)
def team_matches(
    team_id: str, cursor: str | None = None, limit: int = Query(30, ge=1, le=100)
) -> dict[str, Any]:
    items, nxt = repo.matches_for_team(team_id, limit=limit, cursor=cursor)
    if not items and cursor is None:
        team(team_id)
    return {"items": items, "next": nxt}


@teams.get("/{team_id}/form", summary="Last five results")
def team_form(team_id: str) -> dict[str, Any]:
    items, _ = repo.matches_for_team(team_id, limit=5)
    form = []
    for m in items:
        home = m["home"]["id"] == team_id
        gf, ga = (m["score"][0], m["score"][1]) if home else (m["score"][1], m["score"][0])
        form.append(
            {
                "matchId": m["id"],
                "date": m["date"],
                "opponent": m["away"]["name"] if home else m["home"]["name"],
                "result": "W" if gf > ga else ("D" if gf == ga else "L"),
                "score": f"{gf}-{ga}",
            }
        )
    return {"teamId": team_id, "form": form}


@players.get("/{player_id}", summary="A player's headline career numbers")
def player(player_id: str) -> dict[str, Any]:
    p = repo.get_entity("player", player_id)
    if p is None:
        raise not_found("player", player_id)
    return p


@players.get("/{player_id}/seasons", summary="Career, one row per competition-season")
def player_seasons(player_id: str) -> dict[str, Any]:
    p = player(player_id)
    t0 = time.perf_counter()
    rows = queries.player_seasons(player_id)
    names = {c["id"]: c for c in deps.catalog("competitions") or []}
    for r in rows:
        comp = names.get(str(r["competitionId"]))
        r["competition"] = comp["name"] if comp else str(r["competitionId"])
        season = next(
            (s for s in (comp or {}).get("seasons", []) if s["id"] == str(r["seasonId"])), None
        )
        r["season"] = season["name"] if season else str(r["seasonId"])
    return {"player": p, "seasons": rows, "queryMs": round((time.perf_counter() - t0) * 1000, 1)}


@players.get("/{player_id}/shots", summary="Every shot a player took in the archive")
def player_shots(player_id: str, limit: int = Query(400, ge=1, le=2000)) -> list[dict[str, Any]]:
    player(player_id)
    return queries.player_shots(player_id, limit)


@analytics.get("/metrics", summary="Metrics the leaderboard can rank by")
def metrics() -> list[dict[str, str]]:
    return [{"id": k, "description": v[1]} for k, v in queries.LEADERBOARD_METRICS.items()]


@analytics.get("/leaderboard", response_model=Leaderboard, summary="Rank players by any metric")
def leaderboard(
    metric: str = Query("goals"),
    competition: int | None = None,
    season: int | None = None,
    limit: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    """Computed live by DuckDB over the Parquet archive - roughly 14 million
    events, no pre-aggregation, typically well under two seconds."""
    if metric not in queries.LEADERBOARD_METRICS:
        raise ApiError(
            400,
            "unknown_metric",
            f"There is no metric {metric!r}. Try one of: {', '.join(queries.LEADERBOARD_METRICS)}.",
            {"metric": metric},
        )
    t0 = time.perf_counter()
    key = f"lb:{metric}:{competition}:{season}:{limit}"
    rows = deps.cached(
        key,
        600,
        lambda: queries.leaderboard(
            metric, competition_id=competition, season_id=season, limit=limit
        ),
    )
    return {
        "metric": metric,
        "description": queries.LEADERBOARD_METRICS[metric][1],
        "competitionId": competition,
        "seasonId": season,
        "rows": rows,
        "queryMs": round((time.perf_counter() - t0) * 1000, 1),
    }


@analytics.get("/shots", summary="Ad-hoc shot query across the archive")
def shots(
    competition: int | None = None,
    season: int | None = None,
    player: str | None = None,
    min_xg: float = Query(0.0, ge=0, le=1),
    outside_box: bool = False,
    body_part: str | None = Query(None, examples=["Head", "Left Foot", "Right Foot"]),
    limit: int = Query(500, ge=1, le=5000),
) -> dict[str, Any]:
    t0 = time.perf_counter()
    rows = queries.shots(
        competition_id=competition,
        season_id=season,
        player_id=player,
        min_xg=min_xg,
        outside_box=outside_box,
        body_part=body_part,
        limit=limit,
    )
    return {
        "items": rows,
        "count": len(rows),
        "queryMs": round((time.perf_counter() - t0) * 1000, 1),
    }
