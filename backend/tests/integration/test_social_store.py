"""The social store and worker against Redis (fakeredis): de-duplication, the
per-account cap, paging, the dashboard overview, and a failing source."""

from __future__ import annotations

import json
import time

from onside.social import store
from onside.social.base import Plan
from onside.workers import fixtures, social


def post(i, *, handle="@fan", text=None, network="bluesky", topics=("PL",), lang="en", age=0):
    ts = time.time() - age - i
    return {
        "id": f"{network}:{i}", "network": network, "url": f"https://example/{i}",
        "author": {"name": "Fan", "handle": handle, "avatar": "", "url": ""},
        "text": text or f"Arsenal v Chelsea, thought number {i}", "createdAt": "", "ts": ts,
        "lang": lang, "metrics": {"likes": 0, "reposts": 0, "replies": 0}, "media": [],
        "topics": list(topics), "via": "",
    }


def test_the_same_words_from_the_same_account_are_stored_once(redis_fake):
    spam = [post(i, text="Valencia 2-3 Real Sociedad https://spam.example/" + str(i)) for i in range(6)]
    assert store.save(redis_fake, spam) == 1


def test_one_account_cannot_bury_everyone_else(redis_fake):
    store.save(redis_fake, [post(i, handle="@busybot") for i in range(20)])
    store.save(redis_fake, [post(100 + i, handle=f"@fan{i}") for i in range(3)])
    items, _ = store.page(redis_fake, limit=100)
    assert sum(p["author"]["handle"] == "@busybot" for p in items) == store.AUTHOR_CAP
    assert sum(p["author"]["handle"].startswith("@fan") for p in items) == 3


def test_a_post_found_twice_keeps_both_topics(redis_fake):
    a, b = post(1, topics=("fd-1",)), post(1, topics=("PL",))
    store.save(redis_fake, [a, b])
    items, _ = store.page(redis_fake, topic="fd-1")
    assert items[0]["topics"] == ["fd-1", "PL"]


def test_paging_filters_and_walks_newest_first(redis_fake):
    posts = [post(i, handle=f"@f{i}", network="mastodon" if i % 2 else "bluesky",
                  lang="pt" if i % 3 == 0 else "en") for i in range(40)]
    store.save(redis_fake, posts)
    first, cursor = store.page(redis_fake, limit=10)
    second, _ = store.page(redis_fake, limit=10, before=cursor)
    assert [p["ts"] for p in first] == sorted((p["ts"] for p in first), reverse=True)
    assert first[-1]["ts"] > second[0]["ts"]
    only_masto, _ = store.page(redis_fake, network="mastodon", limit=100)
    assert only_masto and all(p["network"] == "mastodon" for p in only_masto)
    english, _ = store.page(redis_fake, lang="en", limit=100)
    assert english and all(p["lang"] == "en" for p in english)


def test_the_overview_counts_trends_volume_and_topics(redis_fake):
    store.set_topics(redis_fake, [{"id": "PL", "label": "Premier League", "kind": "competition"}])
    store.save(redis_fake, [post(i, handle=f"@f{i}", text=f"#COYG what a win number {i}") for i in range(5)])
    store.set_source(redis_fake, "bluesky", "on", "Searching.", 5)
    ov = store.overview(redis_fake)
    assert ov["trends"][0] == {"tag": "coyg", "posts": 5}
    assert ov["topics"][0]["posts"] == 5
    assert sum(h["bluesky"] for h in ov["volume"]) == 5
    assert ov["sources"]["bluesky"]["state"] == "on"
    assert ov["sources"]["reddit"]["state"] == "off"  # never heard from: says so


class Good:
    name = "mastodon"

    def state(self):
        return "on", "fine"

    def collect(self, plan: Plan):
        return [post(1, network="mastodon", handle="@m")]


class Broken:
    name = "bluesky"

    def state(self):
        return "on", "fine"

    def collect(self, plan: Plan):
        raise RuntimeError("upstream exploded at https://secret.example/?token=abc")


class Off:
    name = "x"

    def state(self):
        return "paid_off", "X has no free API."

    def collect(self, plan: Plan):
        raise AssertionError("an off source must not be called")


def test_a_failing_source_is_reported_and_the_others_carry_on(redis_fake):
    redis_fake.set(fixtures.KEY, json.dumps({"matches": []}))
    counts = social.cycle(redis_fake, [Broken(), Good(), Off()])
    assert counts == {"mastodon": 1}
    states = {k: json.loads(v) for k, v in redis_fake.hgetall("social:sources").items()}
    assert states["bluesky"]["state"] == "error"
    assert "secret.example" not in states["bluesky"]["message"]  # never leak a URL
    assert states["x"]["state"] == "paid_off"
