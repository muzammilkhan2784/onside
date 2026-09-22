"""Match endpoints: state, timeline, report, win probability, shots, passing,
stats, corrections, the raw event log and the "was it ever 2-1?" query."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Query

from ...archive.duck import is_compacted
from ...archive.duck import query as duck_query
from ...config import settings
from ...domain.match_state import project_until
from ...store import codec, repo
from .. import deps
from ..errors import ApiError
from ..schemas import Correction, MatchCard, ScoreAt, WinProbability

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("", response_model=list[MatchCard], summary="Matches on a date, all competitions")
def matches_on_date(
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", examples=["2022-12-18"]),
) -> list[dict[str, Any]]:
    """Every archived match played on `date`, across all competitions.

    An empty list is a normal answer - the archive covers selected competitions,
    not every fixture in the world.
    """
    return repo.matches_on_date(date)


@router.get("/{match_id}", summary="Match state")
def match(match_id: str) -> dict[str, Any]:
    """Score, clock, status, goals (including disallowed ones), cards, lineups,
    both sides' metrics with plain-English glosses, and the corrections applied.

    A live match also carries `seq`, the last message number on its WebSocket
    channel: subscribe with `?since=<seq>` to continue exactly from this state.
    """
    state = deps.match_state(match_id)
    if match_id.startswith("live-"):
        from ...streams import bus

        r = bus.sync_client()
        state = {**state, "seq": int(r.get(f"seq:{bus.channel(match_id)}") or 0)}
        state["replay"] = _replay_info(r, match_id)
    return state


def _replay_info(r: Any, lid: str) -> dict[str, Any]:
    """What a replay page needs so it can never be mistaken for a match being
    played today: whether it is still playing, and the real, archived result."""
    from ...streams import bus

    h = bus.replay_state(r, lid)
    of = lid.removeprefix("live-")
    original = repo.get_card(of) or {}
    return {
        "of": of,
        "status": h.get("status", "stopped"),
        "speed": float(h.get("speed") or 0),
        "minute": int(h.get("minute") or 0),
        "original": {
            "date": original.get("date", ""),
            "score": original.get("score"),
            "shootout": original.get("shootout"),
        },
    }


@router.get("/{match_id}/timeline", summary="Display timeline, corrections marked")
def timeline(match_id: str) -> list[dict[str, Any]]:
    return deps.match_state(match_id)["timeline"]


@router.get(
    "/{match_id}/corrections",
    response_model=list[Correction],
    summary="Every correction, with reason and authority",
)
def corrections(match_id: str) -> list[dict[str, Any]]:
    """Archived matches have none: StatsBomb open data records no VAR decisions.
    Replays with an injected VAR check list theirs here, flagged `synthesised`."""
    return deps.match_state(match_id).get("corrections") or []


@router.get("/{match_id}/report", summary="The generated match report")
def report(match_id: str) -> dict[str, Any]:
    """Moments ranked by how far they moved the win probability, templated into
    prose. No language model; it regenerates whenever a correction lands."""
    return deps.match_part(match_id, "REPORT").get("report") or {}


@router.get(
    "/{match_id}/win-probability",
    response_model=WinProbability,
    summary="Per-minute win probability",
)
def win_probability(match_id: str) -> dict[str, Any]:
    body = deps.match_part(match_id, "WPSERIES")
    return {
        "matchId": match_id,
        "range": body.get("winProbabilityRange", ""),
        "series": body.get("winProbability") or [],
    }


@router.get("/{match_id}/shots", summary="Shots with xG and freeze-frames")
def shots(match_id: str, min_xg: float = Query(0.0, ge=0, le=1)) -> list[dict[str, Any]]:
    return [
        s
        for s in deps.match_part(match_id, "SHOTS").get("shots") or []
        if (s.get("xg") or 0) >= min_xg
    ]


@router.get("/{match_id}/pass-network", summary="Pass network for one side")
def pass_network(match_id: str, team: Literal["home", "away"] = "home") -> dict[str, Any]:
    net = (deps.match_part(match_id, "PASSNET").get("passNetwork") or {}).get(team)
    return net or {
        "nodes": [],
        "edges": [],
        "note": "No pass network could be drawn for this side.",
    }


@router.get("/{match_id}/stats", summary="Both sides' metrics")
def stats(match_id: str) -> dict[str, Any]:
    s = deps.match_state(match_id)
    return {"home": s["stats"]["home"], "away": s["stats"]["away"], "glossary": s["glossary"]}


@router.get(
    "/{match_id}/score-at",
    response_model=ScoreAt,
    summary="What the score was at any moment - including before a correction",
)
def score_at(
    match_id: str, minute: int = Query(..., ge=0, le=130), period: int = Query(..., ge=1, le=5)
) -> dict[str, Any]:
    """The question a scores site that overwrites a row cannot answer.

    For a live match this folds the append-only log up to the given moment, so
    a goal that was later disallowed still counts at a minute before the VAR
    decision.
    """
    if match_id.startswith("live-"):
        events, corrs = repo.read_log(match_id)
        state = project_until([*events, *corrs], period, minute)
        home_id = state.home.id if state.home else ""
        goals = [
            {
                "minute": g.minute,
                "player": g.scorer,
                "home": g.team_id == home_id,
                "disallowed": g.disallowed,
            }
            for g in state.goals
        ]
        return {
            "matchId": match_id,
            "period": period,
            "minute": minute,
            "score": list(state.score),
            "goalsSoFar": goals,
        }
    s = deps.match_state(match_id)
    goals = [g for g in s["goals"] if (g["period"], g["minute"]) <= (period, minute)]
    h = sum(1 for g in goals if g["home"] and not g["disallowed"])
    a = sum(1 for g in goals if not g["home"] and not g["disallowed"])
    return {
        "matchId": match_id,
        "period": period,
        "minute": minute,
        "score": [h, a],
        "goalsSoFar": goals,
        "note": "Archived matches carry no corrections, so this is also the score as it stood.",
    }


@router.get("/{match_id}/events", summary="The full event log, filterable")
def events(
    match_id: str,
    type: str | None = Query(None, examples=["Shot"]),
    player: str | None = Query(None, description="Player id"),
    period: int | None = Query(None, ge=1, le=5),
    min_xg: float | None = Query(None, ge=0, le=1),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Every event: passes, carries, pressures, duels, shots - with pitch
    coordinates. Archived matches are read from the Parquet archive by DuckDB,
    pruned to the single file for this match; live matches from the event log."""
    t0 = time.perf_counter()
    if match_id.startswith("live-"):
        evs, _ = repo.read_log(match_id)
        rows = [codec.event_to_dict(e) for e in sorted(evs, key=lambda e: e.sort_key)]
        rows = [
            r
            for r in rows
            if (not type or r["type"] == type)
            and (not player or (r.get("player") or {}).get("id") == player)
            and (not period or r["period"] == period)
            and (min_xg is None or ((r.get("shot") or {}).get("xg") or 0) >= min_xg)
        ]
        return {
            "matchId": match_id,
            "total": len(rows),
            "items": rows[offset : offset + limit],
            "queryMs": round((time.perf_counter() - t0) * 1000, 1),
        }

    card = repo.get_card(match_id)
    if card is None:
        deps.match_state(match_id)  # 404
        raise ApiError(404, "events_not_found", "This match has no archived events.")
    root = settings().archive_uri.rstrip("/")
    if is_compacted(root):  # one file for the whole archive: filter it to this match
        source, where, params = "events", ["match_id = ?"], [int(match_id)]
    else:  # a file per match: read just that one
        source, where, params = (
            f"read_parquet('{root}/competition_id={card['competition']['id']}"
            f"/season_id={card['season']['id']}/match_id={match_id}.parquet')",
            ["1=1"],
            [],
        )
    if type:
        where.append("type = ?")
        params.append(type)
    if player:
        where.append("player_id = ?")
        params.append(player)
    if period:
        where.append("period = ?")
        params.append(period)
    if min_xg is not None:
        where.append("coalesce(shot_xg, 0) >= ?")
        params.append(min_xg)
    cond = " AND ".join(where)
    total = duck_query(f"SELECT count(*) AS n FROM {source} WHERE {cond}", params)[0]["n"]
    rows = duck_query(
        f"SELECT * FROM {source} WHERE {cond} ORDER BY idx LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {
        "matchId": match_id,
        "total": total,
        "items": rows,
        "queryMs": round((time.perf_counter() - t0) * 1000, 1),
    }
