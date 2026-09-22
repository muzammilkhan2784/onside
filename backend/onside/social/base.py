"""The shape every source produces, and the rules every post passes.

A post is a plain dict so it round-trips through Redis and the API untouched:

    {"id", "network", "url", "author": {"name", "handle", "avatar", "url"},
     "text", "createdAt", "ts", "lang", "metrics": {"likes", "reposts", "replies"},
     "media": [{"thumb", "alt"}], "topics": [...], "via": "..."}

`text` is always plain text - HTML from Mastodon is flattened here, on the
server - so the web app renders it as text and never as markup.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Protocol

Post = dict[str, Any]

USER_AGENT = "Onside/1.0 (portfolio project; +https://github.com/muzammilkhan2784/onside)"
MAX_AGE_S = 72 * 3600

#: Posts carrying any of these labels are never shown. "!no-unauthenticated"
#: is Bluesky's opt-out: the author has asked not to be shown to people who
#: are not logged in, which is everyone reading Onside.
BLOCKED_LABELS = frozenset(
    {"porn", "sexual", "nudity", "graphic-media", "gore", "nsfl", "!no-unauthenticated", "!hide"}
)

FOOTBALL_TERMS = re.compile(
    r"\b(football|soccer|futbol|fútbol|fussball|goal|goals|scored|scorer|match|matchday|"
    r"fixture|kick-?off|half-?time|full-?time|penalty|var|derby|league|cup|keeper|striker|"
    r"midfielder|defender|manager|transfer|lineup|line-up|xi|stadium|clean sheet|hat-?trick)\b",
    re.IGNORECASE,
)
HASHTAG = re.compile(r"#\w+")

#: Nicknames too common to identify a team on their own ("city", "united").
#: They count only for a post already found by searching for that fixture.
WEAK_ALIASES = frozenset(
    {"city", "united", "reds", "blues", "madrid", "forest", "afc", "cfc", "om", "inter", "milan"}
)


def fold(s: str) -> str:
    """Lower-case and strip accents, so 'Atlético' matches 'atletico'."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


class _Flatten(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            self.out.append("\n\n")

    def handle_data(self, data: str) -> None:
        self.out.append(data)


def plain_text(markup: str) -> str:
    """Mastodon's HTML as readable plain text: paragraphs and line breaks
    kept, every tag and attribute dropped."""
    p = _Flatten()
    p.feed(markup or "")
    text = html.unescape("".join(p.out))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_time(value: str) -> float:
    """ISO 8601 (with Z or an offset) to a Unix timestamp; 0 if unreadable."""
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


@dataclass(frozen=True)
class Topic:
    """Something posts can be about: one fixture, or one competition."""

    id: str
    label: str
    kind: str  # "fixture" | "competition"
    competition: str = ""
    home: tuple[str, ...] = ()  # aliases, folded
    away: tuple[str, ...] = ()
    names: tuple[str, ...] = ()  # competition aliases, folded
    meta: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)


def _mentions(text: str, aliases: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![\w]){re.escape(a)}(?![\w])", text) for a in aliases if a)


def classify(text: str, topics: list[Topic], via: str = "") -> list[str]:
    """The topics a post is about. A fixture needs both teams named - or one,
    when the post was found by searching for that fixture. A competition needs
    its name, or a fixture of its own. Empty means "not about anything we show"."""
    folded = fold(text)
    hits: list[str] = []
    for t in topics:
        if t.kind != "fixture":
            continue
        home_strong = tuple(x for x in t.home if x not in WEAK_ALIASES)
        away_strong = tuple(x for x in t.away if x not in WEAK_ALIASES)
        both_named = _mentions(folded, home_strong) and _mentions(folded, away_strong)
        found_for_it = via == t.id and (_mentions(folded, t.home) or _mentions(folded, t.away))
        if both_named or found_for_it:
            hits.append(t.id)
    comps_of_hits = {t.competition for t in topics if t.id in hits}
    for t in topics:
        if t.kind == "competition" and (
            t.id in comps_of_hits or _mentions(folded, t.names) or via == t.id
        ):
            hits.append(t.id)
    return hits


def is_football(text: str, topics_hit: list[str]) -> bool:
    """A post we can place is football by definition. Otherwise it needs a
    football word outside its hashtags - '#football' alone on a drawing of a
    cat does not count."""
    if topics_hit:
        return True
    return bool(FOOTBALL_TERMS.search(HASHTAG.sub(" ", text)))


def blocked(labels: list[str] | None) -> bool:
    return bool(BLOCKED_LABELS.intersection(labels or []))


@dataclass
class Plan:
    """What to look for this cycle, per source."""

    topics: list[Topic]
    bluesky: list[tuple[str, str]]  # (query, via topic id)
    mastodon: list[tuple[str, str]]  # (hashtag, via topic id)
    x: list[tuple[str, str]]


class Source(Protocol):
    name: str

    def state(self) -> tuple[str, str]:
        """("on" | "needs_key" | "paid_off" | "error", a sentence for people)."""
        ...

    def collect(self, plan: Plan) -> list[Post]: ...
