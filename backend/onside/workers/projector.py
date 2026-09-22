"""Rebuild a live match from its log and tell everyone what changed.

    log (events + corrections)
        │  project + features + model + report  (pure, ~40 ms for a full match)
        ▼
    new document ──diff──▶ previous document
        │                        │
        ▼                        ▼
    conditional write       publish the *diff* on match:<id>

Publishing the diff rather than a snapshot is the point: a client renders
"Goal disallowed - the score is now 1-1" instead of silently swapping a number.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

from ..ingest.document import build_document
from ..store import repo
from ..streams import bus

log = logging.getLogger("onside.projector")

MAX_RETRIES = 5


def live_meta(match_id: str, r: redis.Redis | None = None) -> dict[str, Any] | None:
    """The StatsBomb match record a replay registered for this live id."""
    r = r or bus.sync_client()
    raw = r.get(f"live:meta:{match_id}")
    return json.loads(raw) if raw else None


def live_lineups(match_id: str, r: redis.Redis | None = None) -> list[dict[str, Any]]:
    r = r or bus.sync_client()
    raw = r.get(f"live:lineups:{match_id}")
    return json.loads(raw) if raw else []


def diff(before: dict[str, Any] | None, after: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn two documents into the messages a client needs, most important first."""
    mid = after["id"]
    msgs: list[dict[str, Any]] = []
    prev_score = before["score"] if before else [0, 0]
    prev_corr = {c["id"] for c in (before or {}).get("corrections", [])}

    for c in after.get("corrections", []):
        if c["id"] in prev_corr:
            continue
        goal = next((g for g in after["goals"] if g["eventId"] == c["supersedes"]), None)
        msgs.append(
            {
                "type": "correction_applied",
                "matchId": mid,
                "correction": c,
                "scoreBefore": prev_score,
                "scoreAfter": after["score"],
                "goal": goal,
                "message": _correction_message(c, goal, after),
            }
        )

    prev_tl = {(t["kind"], t["eventId"]) for t in (before or {}).get("timeline", [])}
    new_items = [
        t
        for t in after["timeline"]
        if (t["kind"], t["eventId"]) not in prev_tl and t["kind"] != "correction"
    ]
    if new_items:
        msgs.append({"type": "event_appended", "matchId": mid, "items": new_items})

    clock_changed = not before or before.get("clock") != after.get("clock")
    if (
        clock_changed
        or prev_score != after["score"]
        or (before or {}).get("status") != after["status"]
    ):
        msgs.append(
            {
                "type": "state_changed",
                "matchId": mid,
                "score": after["score"],
                "shootout": after.get("shootout"),
                "status": after["status"],
                "clock": after["clock"],
                "stats": after["stats"],
                "version": after["version"],
            }
        )

    minute = min(after["clock"]["minute"], 90)
    wp = after["winProbability"][minute] if after["winProbability"] else None
    prev_wp = before["winProbability"][min(before["clock"]["minute"], 90)] if before else None
    if wp and wp != prev_wp:
        msgs.append(
            {
                "type": "wp_updated",
                "matchId": mid,
                "minute": minute,
                "point": wp,
                "series": after["winProbability"][: minute + 1]
                if any(m["type"] == "correction_applied" for m in msgs)
                else None,
            }
        )

    if (
        not before
        or before["report"]["lines"] != after["report"]["lines"]
        or before["report"]["lede"] != after["report"]["lede"]
    ):
        msgs.append({"type": "report_regenerated", "matchId": mid, "report": after["report"]})
    return msgs


def _correction_message(c: dict[str, Any], goal: dict[str, Any] | None, doc: dict[str, Any]) -> str:
    h, a = doc["score"]
    if c["kind"] == "disallow" and goal:
        return (
            f"Goal disallowed - {goal['player']}'s goal at {goal['minute']}' has been ruled out "
            f"({c['reason'].lower()}). The score is now {h}-{a}."
        )
    if c["kind"] == "reinstate" and goal:
        return (
            f"Goal reinstated - {goal['player']}'s goal stands after all. The score is now {h}-{a}."
        )
    return f"{c['headline']}. The score is unchanged."


def project_log(
    match_id: str,
    events: list[Any],
    corrections: list[Any],
    *,
    before: dict[str, Any] | None,
    r: redis.Redis | None = None,
) -> dict[str, Any] | None:
    """Project a match from a log the caller already holds, write it, publish
    the diff. The worker owning the match's shard calls this with its
    in-memory log, so a projection never re-reads the log from DynamoDB.
    """
    r = r or bus.sync_client()
    meta = live_meta(match_id, r)
    if meta is None:
        log.warning("no live metadata for %s; skipping projection", match_id)
        return None
    doc = build_document(
        events,
        meta,
        raw_lineups=live_lineups(match_id, r),
        elo_diff=float(meta.get("_elo_diff", 0.0)),
        corrections=corrections,
        live=True,
    )
    doc["replay"] = meta.get("_replay", {})
    expected = before.get("version") if before else repo.state_version(match_id)
    repo.write_projection(doc, expected)  # raises VersionConflict if we were overtaken
    for msg in diff(before, doc):
        bus.publish(bus.channel(match_id), msg, r)
    if before is None or before.get("score") != doc["score"]:
        bus.publish(
            "feed", {"type": "score_changed", "matchId": match_id, "card": repo.match_card(doc)}, r
        )
    return doc


def project_match(match_id: str, r: redis.Redis | None = None) -> dict[str, Any] | None:
    """Cold-path projection: read the whole log from the store, then project.
    Used by the reclaimer and by tools; workers use `project_log`."""
    events, corrections = repo.read_log(match_id)
    if not events:
        return None
    for _attempt in range(MAX_RETRIES):
        try:
            return project_log(
                match_id, events, corrections, before=repo.get_document(match_id), r=r
            )
        except repo.VersionConflict:
            events, corrections = repo.read_log(match_id)
    log.error("gave up projecting %s after %d version conflicts", match_id, MAX_RETRIES)
    return None
