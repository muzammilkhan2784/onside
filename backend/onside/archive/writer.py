"""Canonical events -> Parquet.

DynamoDB is the wrong tool for "every shot Messi took from outside the box in
La Liga, grouped by season" - that is an analytical scan. Finished matches are
written here as columnar Parquet, Hive-partitioned so DuckDB can prune whole
directories before reading a byte:

    events/competition_id=<cid>/season_id=<sid>/match_id=<mid>.parquet

The schema is flat on purpose. Nested structs in Parquet are supported by
DuckDB but make every analytical query longer; the handful of fields analysts
actually filter on are promoted to columns.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..domain.events import CanonicalEvent

SCHEMA = pa.schema(
    [
        ("match_id", pa.int64()),
        ("match_date", pa.string()),
        ("idx", pa.int32()),
        ("period", pa.int8()),
        ("minute", pa.int16()),
        ("second", pa.int8()),
        ("type", pa.string()),
        ("play_pattern", pa.string()),
        ("possession", pa.int32()),
        ("team_id", pa.string()),
        ("team", pa.string()),
        ("player_id", pa.string()),
        ("player", pa.string()),
        ("position", pa.string()),
        ("x", pa.float32()),
        ("y", pa.float32()),
        ("end_x", pa.float32()),
        ("end_y", pa.float32()),
        ("under_pressure", pa.bool_()),
        ("pass_outcome", pa.string()),
        ("pass_type", pa.string()),
        ("pass_length", pa.float32()),
        ("pass_recipient_id", pa.string()),
        ("pass_cross", pa.bool_()),
        ("pass_through_ball", pa.bool_()),
        ("pass_shot_assist", pa.bool_()),
        ("pass_goal_assist", pa.bool_()),
        ("shot_xg", pa.float32()),
        ("shot_outcome", pa.string()),
        ("shot_type", pa.string()),
        ("shot_body_part", pa.string()),
        ("card", pa.string()),
        ("source_feed", pa.string()),
    ]
)


def rows(events: Sequence[CanonicalEvent], match_date: str) -> dict[str, list[object]]:
    cols: dict[str, list[object]] = {f.name: [] for f in SCHEMA}
    for e in events:
        end: tuple[float, ...] = ()
        if e.pass_ is not None:
            end = e.pass_.end_location
        elif e.shot is not None:
            end = e.shot.end_location
        cols["match_id"].append(int(e.match_id))
        cols["match_date"].append(match_date)
        cols["idx"].append(e.index)
        cols["period"].append(e.period)
        cols["minute"].append(e.minute)
        cols["second"].append(e.second)
        cols["type"].append(e.type)
        cols["play_pattern"].append(e.play_pattern)
        cols["possession"].append(e.possession)
        cols["team_id"].append(e.team.id if e.team else None)
        cols["team"].append(e.team.name if e.team else None)
        cols["player_id"].append(e.player.id if e.player else None)
        cols["player"].append(e.player.name if e.player else None)
        cols["position"].append(e.position or None)
        cols["x"].append(e.location[0] if e.location else None)
        cols["y"].append(e.location[1] if e.location else None)
        cols["end_x"].append(end[0] if len(end) >= 1 else None)
        cols["end_y"].append(end[1] if len(end) >= 2 else None)
        cols["under_pressure"].append(e.under_pressure)
        p = e.pass_
        cols["pass_outcome"].append((p.outcome or "Complete") if p else None)
        cols["pass_type"].append(p.pass_type or None if p else None)
        cols["pass_length"].append(p.length if p else None)
        cols["pass_recipient_id"].append(p.recipient.id if p and p.recipient else None)
        cols["pass_cross"].append(p.cross if p else None)
        cols["pass_through_ball"].append(p.through_ball if p else None)
        cols["pass_shot_assist"].append(p.shot_assist if p else None)
        cols["pass_goal_assist"].append(p.goal_assist if p else None)
        s = e.shot
        cols["shot_xg"].append(s.xg if s else None)
        cols["shot_outcome"].append(s.outcome if s else None)
        cols["shot_type"].append(s.shot_type if s else None)
        cols["shot_body_part"].append(s.body_part if s else None)
        cols["card"].append(e.card)
        cols["source_feed"].append(e.source_feed)
    return cols


def partition_path(root: Path, competition_id: int, season_id: int, match_id: int) -> Path:
    return (
        root
        / f"competition_id={competition_id}"
        / f"season_id={season_id}"
        / f"match_id={match_id}.parquet"
    )


def write_match(
    root: Path,
    events: Sequence[CanonicalEvent],
    *,
    competition_id: int,
    season_id: int,
    match_id: int,
    match_date: str,
) -> Path:
    """Write one match. Idempotent: rewriting a match replaces its file."""
    path = partition_path(root, competition_id, season_id, match_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(rows(events, match_date), schema=SCHEMA)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)  # atomic: a reader never sees half a file
    return path
