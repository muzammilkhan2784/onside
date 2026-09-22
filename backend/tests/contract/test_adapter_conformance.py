"""Feed adapter conformance.

One parametrised suite runs against every adapter. Adding a feed means adding
it to `ADAPTERS` and making these pass - not writing a new test file that
asserts whatever that feed happens to do.

The live feeds run against fixtures through an httpx MockTransport, so the
suite needs no network and no keys:

* `football_data_competitions.recorded.json` is a genuine recording of an
  unauthenticated endpoint.
* `*.schema-shaped.json` are built from each provider's published response
  schema, because the endpoints need a key. Each file says so in its
  `_provenance` field.

The rules encoded here are SPEC.md section 12: normalised events validate
against the canonical model, declared capabilities match what is produced, ids
are stable across two fetches, and nothing is invented where a feed is shallow.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from onside.domain.corrections import Correction
from onside.domain.events import CanonicalEvent
from onside.domain.match_state import project
from onside.feeds.api_football import ApiFootballAdapter
from onside.feeds.base import FeedAdapter, FeedCapabilities
from onside.feeds.football_data import FootballDataAdapter
from onside.feeds.statsbomb import StatsBombAdapter
from onside.replay.download import CACHE

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _transport(routes: dict[str, str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, fixture in routes.items():
            if request.url.path.endswith(prefix):
                return httpx.Response(200, json=_fixture(fixture))
        return httpx.Response(404, json={"message": "not in fixtures"})
    return httpx.MockTransport(handler)


def statsbomb() -> tuple[FeedAdapter, str]:
    if not (CACHE / "events" / "3869685.json").exists():
        pytest.skip("StatsBomb events not cached; run onside.replay.download")
    return StatsBombAdapter(), "3869685"


def football_data() -> tuple[FeedAdapter, str]:
    t = _transport({"/competitions": "football_data_competitions.recorded.json",
                    "/matches/419001": "football_data_match.schema-shaped.json"})
    return FootballDataAdapter(api_key="test", transport=t), "419001"


def api_football() -> tuple[FeedAdapter, str]:
    t = _transport({"/fixtures/events": "api_football_events.schema-shaped.json"})
    return ApiFootballAdapter(api_key="test", transport=t), "1035037"


ADAPTERS: list[Callable[[], tuple[FeedAdapter, str]]] = [statsbomb, football_data, api_football]


@pytest.fixture(params=ADAPTERS, ids=lambda f: f.__name__)
def feed(request) -> tuple[FeedAdapter, str]:
    return request.param()


def test_adapter_satisfies_the_protocol(feed):
    adapter, _ = feed
    assert isinstance(adapter, FeedAdapter)
    assert adapter.name


def test_capabilities_are_declared_honestly(feed):
    adapter, _ = feed
    caps = adapter.capabilities()
    assert isinstance(caps, FeedCapabilities)
    assert caps.name and caps.licence, "a feed without a stated licence should not be shipped"
    if caps.is_live:
        assert caps.update_seconds, "a live feed must say how often it updates"
    else:
        assert caps.update_seconds is None


def test_every_normalised_event_carries_provenance(feed):
    adapter, mid = feed
    events = adapter.fetch_events(mid)
    assert events
    for e in events[:500]:
        assert isinstance(e, CanonicalEvent)
        assert e.source_feed == adapter.name and e.source_event_id and e.event_id
        assert e.match_id == mid


def test_events_validate_against_the_canonical_model(feed):
    adapter, mid = feed
    for e in adapter.fetch_events(mid)[:500]:
        assert e.period in (1, 2, 3, 4, 5)
        assert e.minute >= 0
        if e.location is not None:
            assert 0 <= e.location[0] <= 120 and 0 <= e.location[1] <= 80


def test_declared_capabilities_match_what_is_produced(feed):
    adapter, mid = feed
    caps = adapter.capabilities()
    events = adapter.fetch_events(mid)
    shots = [e for e in events if e.shot is not None]
    has_xg = any(s.shot.xg is not None for s in shots)
    has_locations = any(e.location is not None for e in events)
    assert has_xg == caps.has_xg, "produced xG it does not claim, or claims xG it never produces"
    if not caps.has_events:
        assert not has_locations, "a shallow feed must not invent pitch coordinates"
    if caps.has_freeze_frames:
        assert any(s.shot.freeze_frame for s in shots)


def test_ids_are_stable_across_two_fetches(feed):
    adapter, mid = feed
    first = [e.event_id for e in adapter.fetch_events(mid)]
    assert first == [e.event_id for e in adapter.fetch_events(mid)]
    assert len(first) == len(set(first)), "event ids must be unique within a match"


def test_every_adapter_projects_to_a_score(feed):
    """The whole point of normalising: any feed's events fold with the same
    projector into a match state."""
    adapter, mid = feed
    state = project(adapter.fetch_events(mid))
    assert sum(state.score) >= 1


def test_a_feed_without_corrections_says_so(feed):
    adapter, _ = feed
    caps = adapter.capabilities()
    if not caps.has_corrections:
        assert "correction" in caps.explain_missing("has_corrections").lower()


# ---------------------------------------------------------------- feed-specific

def test_football_data_lists_real_competitions():
    adapter, _ = football_data()
    comps = adapter.list_competitions()
    assert len(comps) > 100, "the recorded response lists every competition the API knows"
    assert any(c.name == "Premier League" for c in comps)


def test_football_data_scores_match_the_feed():
    adapter, mid = football_data()
    assert project(adapter.fetch_events(mid)).score == (3, 1)


def test_api_football_turns_a_var_cancellation_into_a_real_correction():
    """The feed that can do what StatsBomb's open data cannot."""
    adapter, mid = api_football()
    records = adapter.normalise_all(adapter.raw_events(mid), mid)
    corrections = [r for r in records if isinstance(r, Correction)]
    assert len(corrections) == 1
    c = corrections[0]
    assert c.kind == "disallow" and c.authority == "VAR" and c.synthesised is False
    assert c.reason == "Offside"
    state = project(records)
    assert state.score == (2, 0), "Saka's goal was cancelled; City's two stand"
    assert [g.scorer for g in state.goals if g.disallowed] == ["B. Saka"]


def test_a_missing_key_fails_in_plain_english():
    from onside.feeds.http import FeedError

    def refuse(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "restricted"})

    adapter = FootballDataAdapter(api_key="", transport=httpx.MockTransport(refuse))
    with pytest.raises(FeedError, match="API key"):
        adapter.fetch_events("1")
