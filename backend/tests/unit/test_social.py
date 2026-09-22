"""The social feed's rules: what a post is about, what is shown at all, and
whose posts are never shown."""

from __future__ import annotations

import time

from onside.social import topics
from onside.social.base import classify, is_football, plain_text
from onside.social.sources import Bluesky, Mastodon, Reddit, X


def fx(fid, home, away, status="live", code="PL", full=None, when=None):
    return {
        "id": fid,
        "status": status,
        "kickoffUtc": when or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "competition": {"id": "2021", "name": "Premier League", "code": code},
        "home": {"id": "1", "name": home, "fullName": full or f"{home} FC", "code": ""},
        "away": {"id": "2", "name": away, "fullName": f"{away} FC", "code": ""},
        "score": [1, 0],
    }


PLAN = topics.plan([fx("fd-1", "Man City", "Man United", full="Manchester City FC")])


# ---------------------------------------------------------------- matching

def test_a_fixture_needs_both_teams_named():
    assert "fd-1" in classify("Manchester City 2-1 Manchester United, what a derby", PLAN.topics)
    assert "fd-1" not in classify("Man City are flying this season", PLAN.topics)


def test_common_nicknames_alone_do_not_place_a_post():
    # "city" and "united" appear in thousands of posts that are not this match.
    assert "fd-1" not in classify("City and United fans agree on one thing", PLAN.topics)


def test_a_post_found_by_the_fixture_search_needs_only_one_team():
    assert "fd-1" in classify("United were awful today", PLAN.topics, via="fd-1")


def test_a_fixture_also_places_the_post_in_its_competition():
    hits = classify("Man City 2-1 Man Utd", PLAN.topics)
    assert hits == ["fd-1", "PL"]


def test_accents_do_not_stop_a_match():
    plan = topics.plan([fx("fd-2", "Atleti", "Barça", code="PD", full="Club Atlético de Madrid")])
    assert "fd-2" in classify("Atletico Madrid v Barcelona tonight", plan.topics)


def test_a_hashtag_alone_does_not_make_a_post_football():
    assert not is_football("my new drawing of a cat #football #art", [])
    assert is_football("Late penalty decides it #football", [])


def test_mastodon_html_becomes_plain_text():
    html = '<p>Goal!<br>2-1 <a href="https://x.y">link</a></p><p>&amp; more</p>'
    assert plain_text(html) == "Goal!\n2-1 link\n\n& more"


# ---------------------------------------------------------------- who is never shown

def mastodon_status(**over):
    base = {
        "uri": "https://m.example/s/1", "url": "https://m.example/@a/1", "created_at": "2026-09-22T10:00:00Z",
        "content": "<p>Arsenal v Chelsea</p>", "visibility": "public", "language": "en",
        "account": {"acct": "a@m.example", "display_name": "A", "url": "https://m.example/@a"},
    }
    return {**base, **over}


def test_mastodon_skips_sensitive_replies_and_people_who_opted_out():
    assert Mastodon.normalise(mastodon_status()) is not None
    assert Mastodon.normalise(mastodon_status(sensitive=True)) is None
    assert Mastodon.normalise(mastodon_status(spoiler_text="spoilers")) is None
    assert Mastodon.normalise(mastodon_status(in_reply_to_id="9")) is None
    assert Mastodon.normalise(mastodon_status(account={"acct": "a", "noindex": True})) is None
    assert Mastodon.normalise(mastodon_status(account={"acct": "a", "discoverable": False})) is None


def bsky_post(labels=(), author_labels=(), reply=False):
    record = {"text": "Arsenal v Chelsea", "createdAt": "2026-09-22T10:00:00Z", "langs": ["en"]}
    if reply:
        record["reply"] = {"root": {}}
    return {
        "uri": "at://did:plc:x/app.bsky.feed.post/3abc",
        "author": {"handle": "fan.bsky.social", "labels": [{"val": v} for v in author_labels]},
        "record": record,
        "labels": [{"val": v} for v in labels],
    }


def test_bluesky_respects_the_logged_out_opt_out_and_content_labels():
    post = Bluesky.normalise(bsky_post())
    assert post and post["url"] == "https://bsky.app/profile/fan.bsky.social/post/3abc"
    assert Bluesky.normalise(bsky_post(author_labels=["!no-unauthenticated"])) is None
    assert Bluesky.normalise(bsky_post(labels=["porn"])) is None
    assert Bluesky.normalise(bsky_post(reply=True)) is None


def test_reddit_skips_nsfw_and_stickied_posts():
    d = {"id": "a", "title": "Match Thread: Arsenal v Chelsea", "permalink": "/r/soccer/a", "created_utc": 1}
    assert Reddit.normalise(d) is not None
    assert Reddit.normalise({**d, "over_18": True}) is None
    assert Reddit.normalise({**d, "stickied": True}) is None


# ---------------------------------------------------------------- off until switched on

def test_sources_without_credentials_say_what_they_need():
    assert Bluesky(handle="", password="").state()[0] == "needs_key"
    assert Reddit(client_id="", secret="").state()[0] == "needs_key"
    assert X(token="", daily_budget=100).state()[0] == "paid_off"
    assert X(token="t", daily_budget=0).state()[0] == "paid_off"  # a token alone spends nothing
    assert Mastodon().state()[0] == "on"


def test_x_never_spends_past_its_daily_budget():
    class FakeRedis:
        def __init__(self):
            self.v = {}

        def get(self, k):
            return self.v.get(k)

    r = FakeRedis()
    x = X(token="t", daily_budget=25, r=r)
    assert x.remaining() == 25
    r.v[x._spent_key()] = 20
    assert x.remaining() == 5
    # Fewer than a page left: collect() must stop before making a request.
    called = []
    x.http = type("H", (), {"get": lambda *a, **k: called.append(1)})()
    assert x.collect(topics.plan([fx("fd-1", "Arsenal", "Chelsea")])) == [] and not called


# ---------------------------------------------------------------- the plan

def test_the_plan_follows_live_matches_first():
    now = time.time()
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 3 * 3600))
    far = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 5 * 86400))
    plan = topics.plan([
        fx("fd-soon", "Arsenal", "Chelsea", status="scheduled", when=later),
        fx("fd-live", "Leeds", "Burnley", status="live"),
        fx("fd-far", "Spurs", "Wolves", status="scheduled", when=far),
    ], now)
    ids = [t.id for t in plan.topics if t.kind == "fixture"]
    assert ids == ["fd-live", "fd-soon"]  # five days away is not news yet
    assert plan.bluesky[0] == ("Leeds Burnley", "fd-live")
    assert ("football", "") in plan.mastodon
    assert plan.x and plan.x[0][1] == "fd-live"


def test_one_failing_query_costs_only_that_query():
    import httpx

    statuses = [{"uri": "https://m.example/s/9", "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "content": "<p>Man City 2-1 Man United</p>", "visibility": "public",
                 "account": {"acct": "fan@m.example"}}]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/football"):
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, json=statuses)

    m = Mastodon(instance="https://m.example", http=httpx.Client(transport=httpx.MockTransport(handler)))
    posts = m.collect(PLAN)
    assert posts and "fd-1" in posts[0]["topics"]

    down = Mastodon(instance="https://m.example", http=httpx.Client(transport=httpx.MockTransport(
        lambda req: (_ for _ in ()).throw(httpx.ConnectError("down", request=req)))))
    import pytest
    with pytest.raises(RuntimeError, match="requests failed"):
        down.collect(PLAN)


def test_a_competition_search_alone_does_not_place_a_post():
    # Bluesky's search for "Serie A" returned a French post about airlines.
    text = "Algérie-Maroc : Air France et Transavia, complices d'un jeu d'exclusion à la Rabat !"
    plan = topics.plan([fx("fd-3", "Milan", "Lecce", code="SA")])
    assert classify(text, plan.topics, via="SA") == []
    assert not is_football(text, [])
    assert classify("Serie A is wide open this year", plan.topics, via="SA") == ["SA"]


def test_a_look_alike_competition_is_not_the_real_one():
    plan = topics.plan([fx("fd-4", "Arsenal", "Leeds")])
    assert classify("FULL TIME: HFX Wanderers 4-1 Inter Toronto - Canadian Premier League", plan.topics) == []
    assert classify("The Premier League title race is on", plan.topics) == ["PL"]
