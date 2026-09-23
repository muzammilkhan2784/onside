"""Today's real fixtures: football-data.org -> worker -> /api/today.

The feed needs a key, so it runs against a schema-shaped fixture through an
httpx MockTransport. The rule under test is the one the whole site keeps: a
real match and a replay are never confused, and nothing the feed did not send
is invented."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx

from onside.feeds.football_data import FootballDataAdapter
from onside.workers import fixtures

FIXTURE = Path(__file__).parent / "fixtures" / "football_data_matches.schema-shaped.json"


def adapter(status: int = 200) -> tuple[FootballDataAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if status != 200:
            return httpx.Response(status, json={"message": "no"})
        return httpx.Response(200, json=json.loads(FIXTURE.read_text(encoding="utf-8")))

    return FootballDataAdapter(api_key="k", transport=httpx.MockTransport(handle)), seen


def test_one_request_covers_every_competition_in_the_window():
    a, seen = adapter()
    cards = a.matches_between("2026-09-21", "2026-09-23")
    assert len(seen) == 1
    assert seen[0].url.path == "/v4/matches"
    assert dict(seen[0].url.params) == {"dateFrom": "2026-09-21", "dateTo": "2026-09-23"}
    assert seen[0].headers["X-Auth-Token"] == "k"
    assert {c["competition"]["code"] for c in cards} == {"PL", "PD"}


def test_fixture_cards_carry_what_the_feed_sends_and_nothing_else():
    a, _ = adapter()
    by_id = {c["id"]: c for c in a.matches_between("2026-09-21", "2026-09-23")}
    live = by_id["fd-600101"]
    assert live["status"] == "live" and live["source"] == "football-data"
    assert live["home"] == {"id": "57", "name": "Arsenal", "fullName": "Arsenal FC", "code": "ARS"}
    assert live["score"] == [1, 0]
    assert "xg" not in live and "minute" not in live  # the feed sends neither
    assert by_id["fd-600202"]["status"] == "finished" and by_id["fd-600202"]["halfTime"] == [1, 0]
    upcoming = by_id["fd-600103"]
    assert upcoming["status"] == "scheduled" and upcoming["score"] == [None, None]
    assert upcoming["stage"] == "Regular Season"


def test_the_window_is_three_days_back_to_six_ahead_in_utc():
    # The feed caps a window at ten days; midweek, yesterday-to-tomorrow is empty.
    assert fixtures.window(dt.date(2026, 1, 1)) == ("2025-12-29", "2026-01-07")


def test_leagues_carry_the_name_people_use_not_the_official_one():
    a, _ = adapter()
    names = {c["competition"]["code"]: c["competition"]["name"]
             for c in a.matches_between("2026-09-21", "2026-09-23")}
    assert names["PD"] == "La Liga"  # the feed says "Primera Division"
    assert names["PL"] == "Premier League"  # already right: left alone


def test_snapshot_is_sorted_by_kickoff():
    a, _ = adapter()
    snap = fixtures.snapshot(a, dt.date(2026, 9, 22))
    assert snap["ok"] and [m["id"] for m in snap["matches"]] == ["fd-600202", "fd-600101", "fd-600103"]


def test_a_refused_key_becomes_a_message_not_a_crash():
    a, _ = adapter(status=403)
    snap = fixtures.snapshot(a, dt.date(2026, 9, 22))
    assert snap["enabled"] and not snap["ok"] and snap["matches"] == []
    assert "API key" in snap["message"]


class CountingAdapter:
    """Stands in for the feed and counts every request the poller makes."""

    def __init__(self):
        self.calls: list[str] = []

    def matches_between(self, a, b):
        self.calls.append(f"matches {a}..{b}")
        return [{"id": f"fd-{a}", "kickoffUtc": f"{a}T12:00:00Z", "competition": {"name": "PL"}}]

    def current_competitions(self):
        self.calls.append("competitions")
        return [{"code": c, "season": {"start": "2000-01-01", "end": "2999-01-01", "matchday": 5}}
                for c in ("PL", "PD", "BL1", "SA", "FL1", "DED")]

    def matchday(self, code, md):
        self.calls.append(f"round {code} {md}")
        return [{"id": f"fd-{code}-{md}", "kickoffUtc": "2026-10-10T14:00:00Z", "competition": {"name": code}}]

    def standings(self, code):
        self.calls.append(f"standings {code}")
        return {"code": code, "tables": []}

    def scorers(self, code):
        self.calls.append(f"scorers {code}")
        return {"code": code, "rows": []}


def test_the_poller_stays_inside_the_free_tier_budget():
    import fakeredis

    redis_fake = fakeredis.FakeRedis(decode_responses=True)
    a = CountingAdapter()
    poller = fixtures.Poller(a, redis_fake)
    poller.tick()
    # Cold start: both windows, the competition list, the big five tables, one scorers list.
    assert len(a.calls) <= 10
    assert {c for c in a.calls if c.startswith("standings")} == {f"standings {c}" for c in fixtures.BURST}
    snap = json.loads(redis_fake.get(fixtures.KEY))
    assert len(snap["matches"]) == 2  # the main window and the ten days after it, merged
    a.calls.clear()
    for _ in range(5):
        poller.tick()
    assert len(a.calls) <= 5 * 5  # at most five requests a tick after the start
    rounds = [c for c in a.calls if c.startswith("round")]
    assert rounds[:2] == ["round PL 6", "round PD 6"]  # one league's next round a minute, biggest first
    snap = json.loads(redis_fake.get(fixtures.KEY))
    assert any(m["id"] == "fd-PL-6" for m in snap["matches"])  # after the break, still visible
    assert sum(c.startswith("matches") for c in a.calls) == 5  # the far window is not re-fetched every minute


def test_a_cold_start_carries_on_where_the_last_run_stopped():
    import fakeredis

    r = fakeredis.FakeRedis(decode_responses=True)
    a = CountingAdapter()
    fixtures.Poller(a, r).tick()
    first = len(a.calls)
    a.calls.clear()
    fixtures.Poller(a, r).tick()  # a fresh process, as a Lambda cold start is
    assert not any(c.startswith("competitions") for c in a.calls)  # no second cold-start burst
    assert len(a.calls) < first
    assert json.loads(r.get(fixtures.STATE))["tick"] == 2


def test_one_failed_request_does_not_blank_the_fixtures():
    import fakeredis

    from onside.feeds.http import FeedError

    class Flaky(CountingAdapter):
        down = False

        def matches_between(self, a, b):
            if self.down:
                raise FeedError("football-data.org timed out")
            return super().matches_between(a, b)

    r = fakeredis.FakeRedis(decode_responses=True)
    a = Flaky()
    fixtures.Poller(a, r).tick()
    good = json.loads(r.get(fixtures.KEY))
    a.down = True
    body = fixtures.Poller(a, r).tick()
    assert not body["ok"]
    assert json.loads(r.get(fixtures.KEY)) == good  # still the last good list, still its old time

    empty = fakeredis.FakeRedis(decode_responses=True)
    fixtures.Poller(a, empty).tick()  # nothing good yet: the failure itself is shown
    assert json.loads(empty.get(fixtures.KEY))["ok"] is False
