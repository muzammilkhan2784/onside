"""DynamoKV - the Redis subset on DynamoDB used by the free-tier deployment.

Every test runs the same commands against fakeredis and against DynamoKV on
moto and expects the same answers: the callers were written for redis-py, so
"behaves like Redis" is the whole specification.
"""

from __future__ import annotations

import time

from onside import config


def test_strings_counters_and_expiry(kv):
    assert kv.get("missing") is None
    assert kv.set("a", "1") is True
    assert kv.get("a") == "1"
    assert kv.set("a", "2", nx=True) in (False, None)  # redis-py answers None
    assert kv.get("a") == "1"
    assert kv.set("b", "x", nx=True, ex=60)
    assert kv.mget(["a", "missing", "b", "a"]) == ["1", None, "x", "1"]
    assert kv.exists("a") == 1 and kv.exists("missing") == 0
    assert [kv.incr("n") for _ in range(3)] == [1, 2, 3]
    assert kv.get("n") == "3"
    assert kv.expire("n", 60)


def test_an_expired_key_reads_as_gone_and_can_be_set_again(dynamo_kv):
    # DynamoDB's TTL sweeper is eventual; reads must not wait for it.
    dynamo_kv.table.put_item(Item={"PK": "old", "SK": "~", "v": "x", "exp": int(time.time()) - 5})
    assert dynamo_kv.get("old") is None
    assert dynamo_kv.mget(["old"]) == [None]
    assert dynamo_kv.set("old", "new", nx=True, ex=60)
    assert dynamo_kv.get("old") == "new"


def test_large_values_round_trip(kv):
    big = '{"matches":[' + ",".join(f'{{"id":"fd-{i}","name":"Café {i}"}}' for i in range(3000)) + "]}"
    kv.set("big", big)
    assert kv.get("big") == big and kv.mget(["big"]) == [big]


def test_hashes_and_sets(kv):
    kv.hset("h", "a", "1")
    kv.hset("h", mapping={"b": "2", "c": "3"})
    assert kv.hget("h", "b") == "2" and kv.hget("h", "zz") is None
    assert kv.hgetall("h") == {"a": "1", "b": "2", "c": "3"}
    assert kv.hgetall("nothing") == {}
    kv.sadd("s", "x", "y", "z")
    kv.srem("s", "y")
    assert kv.smembers("s") == {"x", "z"}


def test_sorted_sets_by_score(kv):
    kv.zadd("z", {f"m{i}": 1000.0 + i for i in range(10)})
    assert kv.zrevrangebyscore("z", "+inf", "-inf", start=0, num=3) == ["m9", "m8", "m7"]
    assert kv.zrevrangebyscore("z", "+inf", "-inf", start=2, num=2) == ["m7", "m6"]
    assert kv.zrevrangebyscore("z", 1005, 1003) == ["m5", "m4", "m3"]
    assert kv.zrevrangebyscore("z", "(1005", "(1003") == ["m4"]
    assert kv.zrevrangebyscore("z", "(1002", "-inf", start=0, num=5, withscores=True) == [
        ("m1", 1001.0),
        ("m0", 1000.0),
    ]
    assert kv.zcount("z", 1004, "+inf") == 6
    assert kv.zcount("z", "(1004", "+inf") == 5
    kv.zremrangebyscore("z", "-inf", 1001.5)
    assert kv.zcount("z", "-inf", "+inf") == 8
    kv.zremrangebyrank("z", 0, -4)  # keep the newest three
    assert kv.zrevrangebyscore("z", "+inf", "-inf") == ["m9", "m8", "m7"]


def test_members_containing_the_separator(kv):
    kv.zadd("tags", {"coyg#bluesky:at://did/1": 5.0, "coyg#mastodon:https://m/#x": 6.0})
    assert kv.zrevrangebyscore("tags", "+inf", "-inf") == [
        "coyg#mastodon:https://m/#x",
        "coyg#bluesky:at://did/1",
    ]


def test_pipelines_run_every_queued_command(kv):
    pipe = kv.pipeline(transaction=False)
    pipe.set("p", "1")
    pipe.zadd("pz", {"a": 1.0})
    pipe.hset("ph", "f", "v")
    pipe.execute()
    assert kv.get("p") == "1" and kv.zcount("pz", "-inf", "+inf") == 1 and kv.hget("ph", "f") == "v"


def test_the_free_tier_api_serves_the_kv_and_turns_replays_off(dynamo_kv, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from onside.api.main import create_app
    from onside.social import store
    from onside.streams import bus
    from onside.workers import fixtures

    monkeypatch.setenv("ONSIDE_KV", "dynamo")
    config.settings.cache_clear()
    monkeypatch.setattr(bus, "sync_client", lambda: dynamo_kv)
    dynamo_kv.set(fixtures.KEY, json.dumps({"enabled": True, "ok": True, "matches": [],
                                            "fetchedAt": time.time()}))
    store.set_source(dynamo_kv, "mastodon", "on", "Reading public timelines.", 0)

    api = TestClient(create_app())
    assert api.get("/api/features").json() == {
        "realtime": False, "replays": False, "current": True, "deployment": "free-tier"
    }
    assert api.get("/api/today").json()["enabled"] is True
    assert api.get("/api/social/overview").json()["sources"]["mastodon"]["state"] == "on"
    refused = api.get("/api/replay/status")
    assert refused.status_code == 503
    assert refused.json()["error"] == "replays_unavailable"
    assert api.get("/health").json()["checks"]["kv"] == "ok"
