"""The compacted archive the Lambda image carries answers every archive query
exactly as the partitioned one does - same rows, same order."""

from __future__ import annotations

import random

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from onside import config
from onside.archive import compact, duck, queries
from onside.archive.writer import SCHEMA, partition_path

PLAYERS = [("p1", "Ada", "Reds"), ("p2", "Bea", "Blues"), ("p3", "Cy", "Reds"), ("p10", "Di", "Blues")]


def build(root) -> None:
    rnd = random.Random(7)
    mid = 100
    for cid, sid in ((43, 106), (43, 3), (2, 27)):
        for m in range(3):
            mid += 1
            rows = {f.name: [] for f in SCHEMA}
            for i in range(120):
                pid, name, team = rnd.choice(PLAYERS)
                shot = rnd.random() < 0.2
                values = {
                    "match_id": mid, "match_date": f"20{10 + m}-0{1 + m}-1{cid % 9}", "idx": i,
                    "period": 1 if i < 60 else 2, "minute": i // 2, "second": 0,
                    "type": "Shot" if shot else "Pass", "team": team, "team_id": team,
                    "player_id": pid, "player": name, "x": float(rnd.randint(80, 119)),
                    "y": float(rnd.randint(10, 70)),
                    "shot_xg": round(rnd.random(), 2) if shot else None,
                    "shot_outcome": rnd.choice(["Goal", "Saved", "Off T"]) if shot else None,
                    "pass_goal_assist": (not shot) and rnd.random() < 0.05,
                    "pass_outcome": None if rnd.random() < 0.8 else "Incomplete",
                }
                for f in SCHEMA:
                    rows[f.name].append(values.get(f.name))
            path = partition_path(root, cid, sid, mid)
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.table(rows, schema=SCHEMA), path)


def answers(monkeypatch, uri: str) -> list:
    monkeypatch.setenv("ONSIDE_ARCHIVE_URI", uri)
    config.settings.cache_clear()
    duck.reset()
    try:
        return [
            queries.player_seasons("p1"),
            queries.player_shots("p2", limit=5),
            queries.leaderboard("goals"),
            queries.leaderboard("goals", competition_id=43, season_id=106, limit=2),
            queries.shots(competition_id=43, limit=7),
            queries.archive_size(),
        ]
    finally:
        duck.reset()
        config.settings.cache_clear()


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_compaction_changes_speed_not_answers(tmp_path, monkeypatch):
    root = tmp_path / "events"
    build(root)
    out = tmp_path / "events.parquet"
    assert compact.compact(str(root), str(out), memory="256MB") == 9 * 120
    assert duck.is_compacted(str(out)) and not duck.is_compacted(str(root))
    partitioned = answers(monkeypatch, str(root))
    compacted = answers(monkeypatch, str(out))
    assert partitioned == compacted
    assert partitioned[0] and partitioned[2]  # the comparison is not of empty lists


def test_rows_are_sorted_by_player_so_a_lookup_skips_most_of_the_file(tmp_path):
    root = tmp_path / "events"
    build(root)
    out = tmp_path / "events.parquet"
    compact.compact(str(root), str(out), memory="256MB")
    ids = pq.read_table(out, columns=["player_id"]).column("player_id").to_pylist()
    assert ids == sorted(ids)
