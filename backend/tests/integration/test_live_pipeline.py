"""The live pipeline end to end: stream -> worker -> log -> projection -> diff,
including a synthesised VAR correction, a redelivered batch, and recovery of
work a dead worker left pending."""

from __future__ import annotations

import dataclasses
import json

import pytest

from onside.feeds.statsbomb import normalise_match
from onside.ingest.build import causal_elo, match_index
from onside.replay import build_timeline
from onside.replay.download import CACHE, fetch_lineups
from onside.replay.var_injector import inject
from onside.store import codec, repo
from onside.streams import bus
from onside.workers.ingest_worker import Worker
from onside.workers.reclaimer import reclaim_once

FINAL = 3869685
LID = f"live-{FINAL}"


@pytest.fixture
def replay_setup(aws, redis_fake):
    path = CACHE / "events" / f"{FINAL}.json"
    if not path.exists():
        pytest.skip("World Cup final not cached")
    events = [dataclasses.replace(e, match_id=LID)
              for e in normalise_match(json.loads(path.read_text(encoding="utf-8")), LID)]
    meta = next(m for m in match_index() if m["match_id"] == FINAL)
    meta = {**meta, "match_id": LID, "_elo_diff": causal_elo(match_index())[FINAL], "_replay": {}}
    redis_fake.set(f"live:meta:{LID}", json.dumps(meta))
    redis_fake.set(f"live:lineups:{LID}", json.dumps(fetch_lineups(FINAL)))
    goals = [e for e in events if e.is_goal and e.period <= 2]
    corrections = inject(events, match_id=LID, disallow=1, amend=0, target_event_id=goals[1].event_id)
    schedule = build_timeline.build(events, corrections)
    bus.ensure_groups(redis_fake)
    return redis_fake, schedule


def _produce(r, items):
    for s in items:
        body = codec.event_to_dict(s.record) if s.kind == "event" else codec.correction_to_dict(s.record)
        bus.produce(s.kind, LID, body, r)


def _drain(worker, r, consumer="w1"):
    stream = bus.stream_for(LID)
    msgs = []
    while True:
        resp = r.xreadgroup(bus.INGEST_GROUP, consumer, {stream: ">"}, count=500)
        if not resp:
            return msgs
        batch = resp[0][1]
        acked = worker.handle(batch)
        if acked:
            r.xack(stream, bus.INGEST_GROUP, *acked)
        msgs += batch


def test_a_replay_through_the_pipeline_lands_the_correction(replay_setup):
    r, schedule = replay_setup
    pubsub_log = f"chanlog:{bus.channel(LID)}"
    # Everything up to just after the VAR decision in the first half.
    first_half = [s for s in schedule if s.record.period == 1]
    _produce(r, first_half)
    worker = Worker(r, "w1")
    _drain(worker, r)

    state = repo.get_document(LID)
    assert state["score"] == [1, 0], "Di Maria's goal was ruled out at 39'"
    assert state["corrections"] and state["corrections"][0]["synthesised"] is True
    goal = next(g for g in state["goals"] if g["disallowed"])
    assert goal["player"].startswith("Ángel Di María") or "Di María" in goal["player"]

    published = [json.loads(f["msg"]) for _, f in r.xrange(pubsub_log)]
    types = [m["type"] for m in published]
    assert "correction_applied" in types
    corr_msg = next(m for m in published if m["type"] == "correction_applied")
    assert corr_msg["scoreAfter"] == [1, 0]
    seqs = [m["seq"] for m in published]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "a strictly increasing channel sequence"


def test_redelivered_events_change_nothing(replay_setup):
    r, schedule = replay_setup
    early = [s for s in schedule if s.kind == "event" and s.record.period == 1 and s.record.minute < 30]
    _produce(r, early)
    worker = Worker(r, "w1")
    _drain(worker, r)
    v1 = repo.get_document(LID)["version"]
    _produce(r, early)  # the feed reconnects and sends it all again
    _drain(worker, r)
    doc = repo.get_document(LID)
    assert doc["version"] == v1
    assert len(repo.read_log(LID)[0]) == len({s.record.event_id for s in early if s.kind == "event"})


def test_work_left_by_a_dead_worker_is_reclaimed(replay_setup):
    r, schedule = replay_setup
    _produce(r, [s for s in schedule if s.kind == "event" and s.record.period == 1 and s.record.minute < 10])
    stream = bus.stream_for(LID)
    # A worker reads a batch and dies before acknowledging it.
    r.xreadgroup(bus.INGEST_GROUP, "doomed", {stream: ">"}, count=500)
    assert r.xpending(stream, bus.INGEST_GROUP)["pending"] > 0
    recovered = reclaim_once(r, min_idle_ms=0)
    assert recovered > 0
    assert r.xpending(stream, bus.INGEST_GROUP)["pending"] == 0
    assert repo.get_document(LID)["version"] > 0
