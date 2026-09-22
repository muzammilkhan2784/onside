"""Export one match as a self-contained demo payload.

The browser demo is not a video and not a mock: it carries the real event
stream, the real model, and enough per-minute state to *recompute* the
win-probability series when a correction lands. That is the whole point - a
correction has to visibly change the numbers, or the demo is not showing the
thing the project is about.

What makes the recompute possible in the browser without shipping 4,407
events: only `score_diff` and `red_card_diff` change when a goal is disallowed
or a card is rescinded. Everything else (xG, shots, possession) is a property
of the shot having happened, which a correction does not undo. So the payload
carries per-minute cumulative arrays for the unaffected features, plus the
goals and cards as filterable lists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain.events import EventType, sorted_canonically
from ..domain.match_state import RED_CARDS, project
from ..feeds.statsbomb import normalise_match
from ..models.features import FEATURE_NAMES, REGULATION_MINUTES, minute_buckets
from ..replay.download import CACHE, nickname_map
from ..replay.var_injector import DISCLAIMER, inject

ROOT = Path(__file__).resolve().parents[3]
ON_TARGET = {"Goal", "Saved", "Saved to Post"}


def _r(v: float | None, n: int = 3) -> float | None:
    return None if v is None else round(float(v), n)


def build_payload(
    match_id: int,
    meta: dict[str, Any],
    *,
    elo_diff: float = 0.0,
    neutral: bool = True,
) -> dict[str, Any]:
    raw = json.loads((CACHE / "events" / f"{match_id}.json").read_text(encoding="utf-8"))
    events = normalise_match(raw, str(match_id), nickname_map(match_id))
    ordered = sorted_canonically(events)
    state = project(events)
    home_id = state.home.id if state.home else ""

    goals: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    shots: list[dict[str, Any]] = []
    subs: list[dict[str, Any]] = []

    # The per-minute match state comes from the same accumulator the training
    # rows use, so the browser cannot be fed features the model never saw.
    n = REGULATION_MINUTES + 1
    acc = minute_buckets(ordered, home_id=home_id)

    for e in ordered:
        is_home = e.team is not None and e.team.id == home_id

        if e.shot is not None:
            if e.location:
                shots.append(
                    {
                        "id": e.event_id,
                        "minute": e.minute,
                        "period": e.period,
                        "team": e.team.name if e.team else "",
                        "home": is_home,
                        "player": e.player.name if e.player else "",
                        "x": _r(e.location[0], 1),
                        "y": _r(e.location[1], 1),
                        "xg": _r(e.shot.xg, 4),
                        "outcome": e.shot.outcome,
                        "type": e.shot.shot_type,
                        "bodyPart": e.shot.body_part,
                        "goal": e.shot.is_goal,
                        "freeze": [
                            {
                                "x": _r(a.x, 1),
                                "y": _r(a.y, 1),
                                "t": a.teammate,
                                "k": a.keeper,
                                "n": a.name,
                            }
                            for a in e.shot.freeze_frame
                        ],
                    }
                )
            if e.shot.is_goal:
                goals.append(
                    {
                        "id": e.event_id,
                        "minute": e.minute,
                        "period": e.period,
                        "team": e.team.name if e.team else "",
                        "home": is_home,
                        "player": e.player.name if e.player else "",
                        "xg": _r(e.shot.xg, 4),
                        "type": e.shot.shot_type,
                        "shootout": e.period == 5,
                    }
                )

        if e.card:
            cards.append(
                {
                    "id": e.event_id,
                    "minute": e.minute,
                    "period": e.period,
                    "team": e.team.name if e.team else "",
                    "home": is_home,
                    "player": e.player.name if e.player else "",
                    "card": e.card,
                    "red": e.card in RED_CARDS,
                }
            )

        if e.type == EventType.SUBSTITUTION.value and e.player:
            subs.append(
                {
                    "minute": e.minute,
                    "period": e.period,
                    "team": e.team.name if e.team else "",
                    "home": is_home,
                    "off": e.player.name,
                    "on": e.substitution_replacement.name if e.substitution_replacement else "",
                }
            )

    corrections = inject(
        events,
        match_id=str(match_id),
        disallow=1,
        amend=1,
        reassign=0,
        target_event_id=_demo_target(goals),
    )

    return {
        "match": {
            "id": str(match_id),
            "home": state.home.name if state.home else "",
            "away": state.away.name if state.away else "",
            "homeId": home_id,
            "awayId": state.away.id if state.away else "",
            "competition": meta.get("competition", ""),
            "stage": meta.get("stage", ""),
            "date": meta.get("date", ""),
            "venue": meta.get("venue", ""),
            "finalScore": list(state.score),
            "shootout": list(state.shootout_score),
            "neutral": neutral,
            "eloDiff": round(elo_diff, 2),
        },
        "features": list(FEATURE_NAMES),
        "minutes": {
            "n": n,
            "xgH": [round(v, 4) for v in acc["xgH"]],
            "xgA": [round(v, 4) for v in acc["xgA"]],
            "shH": [int(v) for v in acc["shH"]],
            "shA": [int(v) for v in acc["shA"]],
            "sotH": [int(v) for v in acc["sotH"]],
            "sotA": [int(v) for v in acc["sotA"]],
            "possDiff": [round(v, 4) for v in acc["possDiff"]],
        },
        "goals": goals,
        "cards": cards,
        "shots": shots,
        "subs": subs,
        "corrections": [
            {
                "id": c.correction_id,
                "supersedes": c.supersedes,
                "kind": c.kind,
                "reason": c.reason,
                "authority": c.authority,
                "period": c.period,
                "decidedAt": c.decided_at_minute,
                "payload": c.payload,
                "synthesised": c.synthesised,
            }
            for c in corrections
        ],
        "disclaimer": DISCLAIMER,
        "attribution": "Event data: StatsBomb Open Data.",
    }


def _demo_target(goals: list[dict[str, Any]]) -> str | None:
    """Pin the demo's disallowed goal to a regulation goal that changes the
    scoreline visibly - the second goal of the match, where the swing is
    biggest and the story is clearest."""
    regulation = [g for g in goals if g["period"] <= 2]
    if len(regulation) >= 2:
        return regulation[1]["id"]
    return regulation[0]["id"] if regulation else None


def main() -> None:
    model_path = ROOT / "models" / "wp_lgbm.json"
    payload = build_payload(
        3869685,
        {
            "competition": "FIFA World Cup 2022",
            "stage": "Final",
            "date": "18 December 2022",
            "venue": "Lusail Stadium",
        },
        elo_diff=0.0,
        neutral=True,
    )
    if model_path.exists():
        payload["model"] = json.loads(model_path.read_text(encoding="utf-8"))

    out = ROOT / "demo" / "match.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    kb = out.stat().st_size / 1024
    print(f"Wrote {out} ({kb:.0f} KB)")
    print(
        f"  {len(payload['goals'])} goals, {len(payload['shots'])} shots, "
        f"{len(payload['cards'])} cards, {len(payload['corrections'])} corrections"
    )
    for c in payload["corrections"]:
        print(f"  correction: {c['kind']} at {c['decidedAt']}' - {c['reason']}")


if __name__ == "__main__":
    main()
