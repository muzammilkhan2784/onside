"""The store and the public API, end to end against in-process DynamoDB."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from onside.store import repo
from onside.store.repo import VersionConflict

from ..conftest import ev  # noqa: TID252 - shared factory

# ---------------------------------------------------------------- store

def test_documents_round_trip_and_every_listing_finds_them(aws, sample_docs):
    repo.put_documents(sample_docs)
    d = sample_docs[0]
    assert repo.get_card(d["id"])["headline"] == d["story"]["headline"]
    full = repo.get_document(d["id"])
    assert full["score"] == d["score"] and len(full["shots"]) == len(d["shots"])
    assert any(c["id"] == d["id"] for c in
               repo.matches_for_competition_season(d["competition"]["id"], d["season"]["id"]))
    assert any(c["id"] == d["id"] for c in repo.matches_on_date(d["date"]))
    assert any(c["id"] == d["id"] for c in repo.matches_for_team(d["home"]["id"])[0])
    feed, _ = repo.feed(limit=50)
    dates = [c["date"] for c in feed]
    assert dates == sorted(dates, reverse=True), "the feed is newest first"


def test_feed_pagination_cursor_walks_every_story_once(aws, sample_docs):
    repo.put_documents(sample_docs)
    seen, cursor = [], None
    while True:
        items, cursor = repo.feed(limit=5, cursor=cursor)
        seen += [c["id"] for c in items]
        if not cursor:
            break
    assert sorted(seen) == sorted(d["id"] for d in sample_docs)
    assert len(seen) == len(set(seen))


def test_appending_the_same_event_twice_is_a_no_op(aws):
    e = ev(minute=10, event_id="evt-1")
    assert repo.append_event(e) is True
    assert repo.append_event(e) is False
    events, _ = repo.read_log(e.match_id)
    assert [x.event_id for x in events] == ["evt-1"]


def test_projection_writes_are_conditional_on_version(aws, sample_docs):
    doc = {**sample_docs[0], "id": "live-9", "live": True, "version": 5}
    repo.write_projection(doc, None)
    with pytest.raises(VersionConflict):
        repo.write_projection({**doc, "version": 6}, 4)  # a stale writer loses
    repo.write_projection({**doc, "version": 6}, 5)
    assert repo.state_version("live-9") == 6


def test_a_replay_never_appears_in_the_archive_listings(aws, sample_docs):
    doc = {**sample_docs[0], "id": "live-777", "live": True, "version": 1}
    repo.put_documents([doc])
    assert [c["id"] for c in repo.live_matches()] == ["live-777"]
    feed, _ = repo.feed(limit=100)
    assert "live-777" not in [c["id"] for c in feed]


def test_archived_matches_cannot_be_deleted(aws):
    with pytest.raises(ValueError):
        repo.delete_match("3869685")


# ---------------------------------------------------------------- API

@pytest.fixture
def api(aws, redis_fake, sample_docs):
    from onside.api import deps
    from onside.api.main import create_app
    from onside.ingest.seed import collections, search_index

    repo.put_documents(sample_docs)
    cards = [repo.match_card(d) for d in sample_docs]
    repo.put_catalog("collections", "all", collections(cards))
    repo.put_catalog("search", "all", search_index(
        [], [{"id": c["home"]["id"], "name": c["home"]["name"], "competitions": [], "matches": 1} for c in cards],
        [{"id": "5503", "name": "Lionel Messi", "teams": ["Barcelona"], "matches": 445},
         {"id": "1", "name": "Messiah Bright", "teams": ["Orlando Pride"], "matches": 20}]))
    repo.put_catalog("stats", "archive", {"matches": len(cards)})
    repo.put_catalog("competitions", "all", [])
    deps._cache.clear()
    with TestClient(create_app()) as client:
        yield client


def test_match_endpoints_serve_the_document(api, sample_docs):
    d = sample_docs[0]
    r = api.get(f"/api/matches/{d['id']}")
    assert r.status_code == 200 and r.json()["score"] == d["score"]
    wp = api.get(f"/api/matches/{d['id']}/win-probability").json()
    assert len(wp["series"]) == 91
    assert api.get(f"/api/matches/{d['id']}/report").json()["headline"]
    assert isinstance(api.get(f"/api/matches/{d['id']}/shots").json(), list)


def test_errors_use_the_envelope_and_speak_plainly(api):
    r = api.get("/api/matches/not-a-match")
    assert r.status_code == 404
    body = r.json()
    assert set(body) == {"error", "message", "detail"}
    assert body["error"] == "match_not_found"
    assert "archive" in body["message"]
    bad = api.get("/api/matches/3869685/score-at?minute=500&period=1").json()
    assert bad["error"] == "invalid_request" and "minute" in bad["message"]
    assert api.get("/no/such/route").json()["error"] == "route_not_found"


def test_search_puts_the_real_messi_first(api):
    names = [h["name"] for h in api.get("/api/search?q=messi").json()]
    assert names[0] == "Lionel Messi", "a word-prefix match with more appearances outranks a name prefix"


def test_score_at_answers_from_the_archive(api):
    r = api.get("/api/matches/3869685/score-at?period=1&minute=40").json()
    assert r["score"] == [2, 0]


def test_low_bandwidth_page_is_under_100kb_and_needs_no_javascript(api):
    r = api.get("/m/3869685")
    assert r.status_code == 200
    assert len(r.content) < 100_000
    html = r.text
    assert "<script" not in html
    assert 'aria-live="polite"' in html and "<time" in html and "<table" in html


def test_replay_start_queues_a_command(api, redis_fake):
    r = api.post("/api/replay/start", json={"match_id": 3869685, "speed": 60, "inject_var": True})
    assert r.status_code == 202 and r.json()["matchId"] == "live-3869685"
    entries = redis_fake.xrange("replay:control")
    assert entries and entries[-1][1]["match"] == "3869685"


def test_replay_start_rejects_unknown_matches(api):
    r = api.post("/api/replay/start", json={"match_id": 1, "speed": 60})
    assert r.status_code == 404 and r.json()["error"] == "match_not_found"


def test_openapi_documents_the_error_envelope(api):
    spec = api.get("/openapi.json").json()
    assert "ErrorEnvelope" in spec["components"]["schemas"]
    assert len(spec["paths"]) >= 35


# ---------------------------------------------------------------- replays tell the truth

def _replay_doc(sample_docs) -> tuple[str, dict]:
    """A replay of whichever real match the archive holds (CI builds only a
    small sample, so this cannot insist on the 2022 final)."""
    d = sample_docs[0]
    lid = f"live-{d['id']}"
    return lid, {**d, "id": lid, "live": True, "version": 1, "status": "live"}


def test_only_replays_that_are_playing_are_listed_as_live(api, sample_docs, redis_fake):
    import time

    lid, doc = _replay_doc(sample_docs)
    repo.put_documents([doc])
    redis_fake.sadd("replays:active", lid)
    state = f"replay:state:{lid}"

    redis_fake.hset(state, mapping={"status": "running", "heartbeat": str(time.time())})
    assert [c["id"] for c in api.get("/api/live").json()] == [lid]

    # Finished: the page still works, but nothing lists it as being played.
    redis_fake.hset(state, mapping={"status": "finished"})
    assert api.get("/api/live").json() == []
    assert api.get("/api/home").json()["live"] == []
    assert api.get(f"/api/matches/{lid}").status_code == 200


def test_a_replay_whose_process_died_reads_as_stopped(api, sample_docs, redis_fake):
    import time

    lid, doc = _replay_doc(sample_docs)
    repo.put_documents([doc])
    redis_fake.sadd("replays:active", lid)
    redis_fake.hset(f"replay:state:{lid}",
                    mapping={"status": "running", "heartbeat": str(time.time() - 600), "minute": "67"})
    assert api.get("/api/live").json() == []
    assert api.get("/api/replay/status").json()[0]["status"] == "stopped"
    body = api.get(f"/api/matches/{lid}").json()
    assert body["replay"]["status"] == "stopped"


def test_a_replay_page_carries_the_real_result(api, sample_docs, redis_fake):
    lid, doc = _replay_doc(sample_docs)
    real = sample_docs[0]
    repo.put_documents([doc])
    info = api.get(f"/api/matches/{lid}").json()["replay"]
    assert info["of"] == real["id"]
    assert info["original"] == {"date": real["date"], "score": real["score"], "shootout": real.get("shootout")}


def test_a_new_feed_socket_starts_from_now_not_from_history(api, redis_fake):
    from onside.streams import bus

    bus.publish("feed", {"type": "score_changed", "matchId": "live-1", "card": {"id": "live-1"}})
    with api.websocket_connect("/ws/feed") as ws:
        assert ws.receive_json()["type"] == "hello"  # no stale score first
    with api.websocket_connect("/ws/feed?since=0") as ws:
        assert ws.receive_json()["type"] == "score_changed"  # asked for history, got it
        assert ws.receive_json()["type"] == "hello"


def test_an_unreachable_archive_is_a_503_that_explains_itself(api, monkeypatch):
    from onside.archive import duck, queries

    def boom(*_a, **_k):
        raise duck.ArchiveUnavailable("NoSuchBucket")

    monkeypatch.setattr(queries, "leaderboard", boom)
    r = api.get("/api/analytics/leaderboard", params={"metric": "goals", "competition": "43", "season": "106"})
    assert r.status_code == 503
    assert r.json()["error"] == "archive_unavailable"
    assert "Match pages are unaffected" in r.json()["message"]


def test_today_explains_itself_when_there_is_no_key(api):
    body = api.get("/api/today").json()
    assert body["enabled"] is False and body["matches"] == []
    assert "FOOTBALL_DATA_API_KEY" in body["message"]


def test_today_serves_what_the_fixtures_worker_cached(api, redis_fake):
    import json
    import time

    card = {"id": "fd-1", "status": "live", "home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}}
    redis_fake.set("fixtures:today", json.dumps(
        {"enabled": True, "ok": True, "matches": [card], "fetchedAt": time.time()}))
    body = api.get("/api/today").json()
    assert body["enabled"] and body["matches"] == [card]
    assert body["source"] == "football-data.org" and body["stale"] is False


def test_current_football_routes_serve_what_the_workers_cached(api, redis_fake):
    import json
    import time

    from onside.workers import fixtures

    today = time.strftime("%Y-%m-%d")
    redis_fake.set(fixtures.COMPETITIONS, json.dumps({"data": [
        {"code": "PL", "id": "2021", "name": "Premier League", "type": "LEAGUE", "area": "England",
         "season": {"start": "2000-01-01", "end": "2999-01-01", "matchday": 5}},
        {"code": "EC", "id": "2018", "name": "European Championship", "type": "CUP", "area": "Europe",
         "season": {"start": "2024-06-14", "end": "2024-07-14", "matchday": 7}},
    ], "fetchedAt": time.time()}))
    redis_fake.set(fixtures.standings_key("PL"), json.dumps(
        {"code": "PL", "tables": [{"stage": "Regular Season", "group": "", "rows": []}], "fetchedAt": time.time()}))
    comps = api.get("/api/current/competitions").json()
    assert [c["code"] for c in comps] == ["PL"]  # a finished tournament is not "current"
    assert comps[0]["hasTable"] and not comps[0]["hasScorers"]
    assert api.get("/api/current/pl/standings").json()["tables"][0]["stage"] == "Regular Season"
    missing = api.get("/api/current/PL/scorers")
    assert missing.status_code == 404 and missing.json()["error"] == "scorers_not_ready"
    assert "try again shortly" in missing.json()["message"]
    assert today  # the window itself is covered in the contract tests


def test_the_social_feed_route_pages_posts(api, redis_fake):
    import time

    from onside.social import store

    posts = [{"id": f"bluesky:{i}", "network": "bluesky", "url": "u", "text": f"Arsenal v Chelsea {i}",
              "author": {"name": "F", "handle": f"@f{i}", "avatar": "", "url": ""}, "createdAt": "",
              "ts": time.time() - i, "lang": "en", "metrics": {}, "media": [], "topics": ["PL"], "via": ""}
             for i in range(5)]
    store.save(redis_fake, posts)
    body = api.get("/api/social", params={"topic": "PL", "limit": 3}).json()
    assert len(body["items"]) == 3 and body["next"]
    rest = api.get("/api/social", params={"topic": "PL", "limit": 3, "before": body["next"]}).json()
    assert len(rest["items"]) == 2 and rest["next"] is None
    ov = api.get("/api/social/overview").json()
    assert ov["total24h"] == 5 and set(ov["sources"]) >= {"bluesky", "mastodon", "reddit", "x"}
