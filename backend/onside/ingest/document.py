"""One match -> the document every page and endpoint reads.

`build_document` is the single place a finished match is turned into what the
product shows: the projected state, the per-minute win probability, the
generated report, the timeline, both sides' metrics, the shot map with
freeze-frames and both pass networks. It is a pure function of its inputs, so
the whole archive can be rebuilt deterministically, and the same code path
serves a replayed match when a correction lands.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..domain.corrections import Correction
from ..domain.events import CanonicalEvent, sorted_canonically
from ..domain.match_state import MatchState, effective_events, project
from ..domain.metrics import GLOSSARY, pass_network, team_metrics, timeline
from ..domain.narrative.writer import write
from ..models.predict import series_for_match

#: International tournaments, played at neutral venues.
NEUTRAL_COMPETITIONS = frozenset({43, 55, 72, 223, 1267, 53, 1470})

FEED_CAPABILITIES = {
    "feed": "StatsBomb Open Data",
    "hasEvents": True,
    "hasXg": True,
    "hasFreezeFrames": True,
    "hasLineups": True,
    "hasCorrections": False,
    "isLive": False,
}


def _r(v: float | None, n: int = 3) -> float | None:
    return None if v is None else round(float(v), n)


def lineups_doc(
    raw_lineups: Sequence[dict[str, Any]], home_id: str
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
    for team in raw_lineups:
        side = "home" if str(team.get("team_id")) == home_id else "away"
        for p in team.get("lineup", []):
            positions = p.get("positions") or []
            start = positions[0] if positions else {}
            out[side].append(
                {
                    "id": str(p["player_id"]),
                    "name": p.get("player_nickname") or p["player_name"],
                    "number": p.get("jersey_number"),
                    "position": start.get("position", ""),
                    "started": start.get("start_reason") == "Starting XI",
                    "country": (p.get("country") or {}).get("name", ""),
                }
            )
        out[side].sort(key=lambda r: (not r["started"], r["number"] or 99))
    return out


def shots_doc(
    events: Sequence[CanonicalEvent], home_id: str, disallowed: set[str] | None = None
) -> list[dict[str, Any]]:
    disallowed = disallowed or set()
    out = []
    for e in events:
        if e.shot is None or e.location is None:
            continue
        out.append(
            {
                "id": e.event_id,
                "period": e.period,
                "minute": e.minute,
                "second": e.second,
                "home": bool(e.team and e.team.id == home_id),
                "team": e.team.name if e.team else "",
                "playerId": e.player.id if e.player else "",
                "player": e.player.name if e.player else "",
                "x": _r(e.location[0], 1),
                "y": _r(e.location[1], 1),
                "endX": _r(e.shot.end_location[0], 1) if e.shot.end_location else None,
                "endY": _r(e.shot.end_location[1], 1) if len(e.shot.end_location) > 1 else None,
                "xg": _r(e.shot.xg, 4),
                "outcome": e.shot.outcome,
                "type": e.shot.shot_type,
                "bodyPart": e.shot.body_part,
                "technique": e.shot.technique,
                "goal": e.shot.is_goal,
                "disallowed": e.event_id in disallowed,
                "shootout": e.period == 5,
                "freeze": [
                    {
                        "x": _r(a.x, 1),
                        "y": _r(a.y, 1),
                        "teammate": a.teammate,
                        "keeper": a.keeper,
                        "name": a.name,
                    }
                    for a in e.shot.freeze_frame
                ],
            }
        )
    return out


def _half_time(state: MatchState) -> list[int]:
    home = state.home.id if state.home else ""
    h = sum(1 for g in state.goals if g.counts and g.period == 1 and g.team_id == home)
    a = sum(1 for g in state.goals if g.counts and g.period == 1 and g.team_id != home)
    return [h, a]


def build_document(
    events: Sequence[CanonicalEvent],
    meta: dict[str, Any],
    *,
    raw_lineups: Sequence[dict[str, Any]] = (),
    elo_diff: float = 0.0,
    wp_series: Sequence[dict[str, float]] | None = None,
    corrections: Sequence[Correction] = (),
    live: bool = False,
) -> dict[str, Any]:
    """Everything about one finished (or replaying) match, as one document.

    `meta` is the StatsBomb match record, augmented with `_competition_*` and
    `_season_*` keys by the ingest. `wp_series` may be passed in when the
    caller has already computed it (the replay path recomputes on correction).
    """
    ordered = sorted_canonically(list(events))
    log: list[Any] = [*ordered, *corrections]
    state = project(log)
    # Corrections move every number, not only the score: features and metrics
    # read the events as the corrections say they should now be read.
    effective = effective_events(log)
    home_id = str(meta["home_team"]["home_team_id"])
    away_id = str(meta["away_team"]["away_team_id"])
    names = {
        home_id: meta["home_team"]["home_team_name"],
        away_id: meta["away_team"]["away_team_name"],
    }
    comp_id = int(meta["_competition_id"])
    neutral = comp_id in NEUTRAL_COMPETITIONS

    series = (
        list(wp_series)
        if wp_series is not None
        else series_for_match(
            effective,
            home_id=home_id,
            away_id=away_id,
            match_id=str(meta["match_id"]),
            elo_diff=elo_diff,
            is_neutral_venue=neutral,
        )
    )
    report = write(
        state,
        ordered,
        series,
        competition=meta["_competition_name"],
        date=meta.get("match_date", ""),
    )
    hm, am = team_metrics(effective, home_id, away_id, names)

    def team_block(side: str) -> dict[str, Any]:
        t = meta[f"{side}_team"]
        mgrs = t.get("managers") or []
        return {
            "id": str(t[f"{side}_team_id"]),
            "name": t[f"{side}_team_name"],
            "country": (t.get("country") or {}).get("name", ""),
            "manager": (mgrs[0].get("nickname") or mgrs[0].get("name")) if mgrs else "",
        }

    sh, sa = state.shootout_score
    doc: dict[str, Any] = {
        "id": str(meta["match_id"]),
        "competition": {
            "id": str(comp_id),
            "name": meta["_competition_name"],
            "gender": meta.get("_competition_gender", ""),
            "international": bool(meta.get("_competition_international")),
        },
        "season": {"id": str(meta["_season_id"]), "name": meta["_season_name"]},
        "date": meta.get("match_date", ""),
        "kickoff": meta.get("kick_off") or "",
        "matchWeek": meta.get("match_week"),
        "stage": (meta.get("competition_stage") or {}).get("name", ""),
        "stadium": (meta.get("stadium") or {}).get("name", ""),
        "referee": (meta.get("referee") or {}).get("name", ""),
        "neutral": neutral,
        "home": team_block("home"),
        "away": team_block("away"),
        "score": list(state.score),
        "halfTime": _half_time(state),
        "shootout": [sh, sa] if state.shootout else None,
        "status": "finished",
        "eloDiff": round(elo_diff, 1),
        "goals": [
            {
                "eventId": g.event_id,
                "period": g.period,
                "minute": g.minute,
                "home": g.team_id == home_id,
                "team": g.team_name,
                "player": g.scorer,
                "playerId": g.scorer_id,
                "xg": _r(g.xg, 3),
                "type": g.shot_type,
                "ownGoal": g.own_goal,
                "disallowed": g.disallowed,
                "correctionReason": g.correction_reason,
                "correctedAt": g.corrected_at_minute,
                "synthesisedCorrection": g.synthesised_correction,
            }
            for g in state.goals
        ],
        "cards": [
            {
                "eventId": c.event_id,
                "period": c.period,
                "minute": c.minute,
                "home": c.team_id == home_id,
                "player": c.player,
                "card": c.card,
            }
            for c in state.cards
        ],
        "timeline": _timeline(ordered, state, home_id),
        "stats": {"home": hm.as_dict(), "away": am.as_dict()},
        "glossary": GLOSSARY,
        "winProbability": series,
        "winProbabilityRange": "Regulation (0-90'). Extra time and penalties are outside the model's range.",
        "report": {
            "headline": report.headline,
            "lede": report.lede,
            "lines": list(report.lines),
            "closing": report.closing,
            "notes": list(report.notes),
            "moments": [
                {
                    "kind": m.kind,
                    "period": m.period,
                    "minute": m.minute,
                    "player": m.player,
                    "team": m.team_name,
                    "swing": round(m.swing, 4),
                    "before": [round(v, 4) for v in m.wp_before],
                    "after": [round(v, 4) for v in m.wp_after],
                }
                for m in report.moments
            ],
        },
        "shots": shots_doc(ordered, home_id, set(state.superseded)),
        "passNetwork": {
            side: {
                "nodes": list(net.nodes),
                "edges": list(net.edges),
                "untilMinute": net.until_minute,
                "note": net.note,
            }
            for side, net in (
                ("home", pass_network(ordered, home_id)),
                ("away", pass_network(ordered, away_id)),
            )
        },
        "lineups": lineups_doc(raw_lineups, home_id) if raw_lineups else {"home": [], "away": []},
        "capabilities": FEED_CAPABILITIES,
        "eventCount": len(ordered),
        "corrections": [
            {
                "id": c.correction_id,
                "supersedes": c.supersedes,
                "kind": c.kind,
                "reason": c.reason,
                "authority": c.authority,
                "period": c.period,
                "decidedAt": c.decided_at_minute,
                "synthesised": c.synthesised,
                "headline": c.headline,
            }
            for c in state.corrections
        ],
        "version": len(ordered) + len(corrections),
        "live": live,
        "clock": {"period": state.period, "minute": state.minute, "second": state.second},
        "source": "statsbomb",
    }
    if live:
        doc["status"] = state.status if state.status != "scheduled" else "live"
        doc["report"]["lede"] = live_lede(doc)
    doc["story"] = story_card(doc)
    return doc


def live_lede(doc: dict[str, Any]) -> str:
    """A report written mid-match speaks in the present tense and never knows
    how the match ends."""
    h, a = doc["score"]
    home, away = doc["home"]["name"], doc["away"]["name"]
    minute = doc["clock"]["minute"]
    if doc["status"] == "finished":
        return doc["report"]["lede"]
    where = "at half-time" if doc["status"] == "half_time" else f"after {minute} minutes"
    if h == a:
        return f"{home} and {away} are level at {h}-{a} {where}."
    lead, trail = (home, away) if h > a else (away, home)
    return f"{lead} lead {trail} {max(h, a)}-{min(h, a)} {where}."


def _timeline(
    ordered: Sequence[CanonicalEvent], state: MatchState, home_id: str
) -> list[dict[str, Any]]:
    """Notable events plus the corrections, each at the minute it happened.
    A disallowed goal stays in its place, flagged - it is never removed."""
    superseded = set(state.superseded)
    reasons = {g.event_id: g for g in state.goals}
    out: list[dict[str, Any]] = []
    for t in timeline(ordered):
        item = {
            "kind": t.kind,
            "period": t.period,
            "minute": t.minute,
            "second": t.second,
            "home": t.team_id == home_id,
            "team": t.team,
            "player": t.player,
            "detail": t.detail,
            "eventId": t.event_id,
            **dict(t.extra.items()),
        }
        if t.kind == "goal" and t.event_id in superseded:
            g = reasons[t.event_id]
            item.update(
                disallowed=True,
                correctionReason=g.correction_reason,
                correctedAt=g.corrected_at_minute,
            )
        out.append(item)
    for c in state.corrections:
        out.append(
            {
                "kind": "correction",
                "period": c.period,
                "minute": c.decided_at_minute,
                "second": 59,
                "home": None,
                "team": "",
                "player": "",
                "detail": c.reason,
                "eventId": c.correction_id,
                "correctionKind": c.kind,
                "authority": c.authority,
                "supersedes": c.supersedes,
                "synthesised": c.synthesised,
            }
        )
    out.sort(key=lambda i: (i["period"], i["minute"], i["second"]))
    return out


def story_card(doc: dict[str, Any]) -> dict[str, Any]:
    """The news-feed card for a match: a headline and a standfirst built from
    the report, plus the tags that decide where it is surfaced."""
    h, a = doc["score"]
    moments = doc["report"]["moments"]
    biggest = max((m["swing"] for m in moments), default=0.0)
    hxg, axg = doc["stats"]["home"]["xg"], doc["stats"]["away"]["xg"]
    tags: list[str] = []
    if doc["shootout"]:
        tags.append("penalties")
    if biggest >= 0.4:
        tags.append("turnaround")
    if h + a >= 5:
        tags.append("goal-fest")
    if (h > a and hxg < axg - 0.8) or (a > h and axg < hxg - 0.8):
        tags.append("smash-and-grab")
    if h == a == 0:
        tags.append("stalemate")
    if doc["stage"] and doc["stage"] not in ("Regular Season", "Group Stage"):
        tags.append("knockout")
    return {
        "headline": doc["report"]["headline"],
        "standfirst": doc["report"]["lede"],
        "biggestSwing": round(biggest, 3),
        "tags": tags,
    }
