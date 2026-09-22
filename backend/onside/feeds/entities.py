"""Cross-feed entity resolution.

The same player is `statsbomb:5503`, `football-data:44` and `api-football:154`.
Resolution runs in tiers, strongest evidence first:

1. A known alias (`ALIAS#<feed>#<id>` in the store, or the curated file) - done.
2. Exact normalised name *and* birth date - link, confidence 1.0.
3. Fuzzy name (token-sorted Jaro-Winkler >= 0.92) *and* the same team - link,
   confidence 0.8.
4. Otherwise: a new canonical entity flagged `needs_review`, surfaced by
   /api/entities/unresolved.

Fuzzy matching does not solve "Rodri" vs "Rodrigo Hernandez Cascante", and
pretending it does is worse than admitting it. Those live in a small, curated
alias file.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ALIASES = Path(__file__).with_name("aliases.json")
FUZZY_THRESHOLD = 0.92


def normalise_name(name: str) -> str:
    """Fold case, strip diacritics and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in s)
    return " ".join(s.split())


def token_sorted(name: str) -> str:
    return " ".join(sorted(normalise_name(name).split()))


def jaro_winkler(a: str, b: str, prefix_scale: float = 0.1) -> float:
    """Jaro-Winkler similarity in [0, 1]. Written out rather than imported: it
    is twenty lines and the resolution thresholds depend on exactly this."""
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    window = max(la, lb) // 2 - 1
    ma, mb = [False] * la, [False] * lb
    matches = 0
    for i, ca in enumerate(a):
        lo, hi = max(0, i - window), min(lb, i + window + 1)
        for j in range(lo, hi):
            if not mb[j] and b[j] == ca:
                ma[i] = mb[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions, k = 0, 0
    for i in range(la):
        if ma[i]:
            while not mb[k]:
                k += 1
            if a[i] != b[k]:
                transpositions += 1
            k += 1
    m = float(matches)
    jaro = (m / la + m / lb + (m - transpositions / 2) / m) / 3
    prefix = 0
    for ca, cb in zip(a[:4], b[:4], strict=False):
        if ca != cb:
            break
        prefix += 1
    return jaro + prefix * prefix_scale * (1 - jaro)


@dataclass(frozen=True, slots=True)
class Candidate:
    canonical_id: str
    name: str
    birth_date: str = ""
    team: str = ""


@dataclass(frozen=True, slots=True)
class Resolution:
    canonical_id: str | None
    confidence: float
    method: str  # alias | exact | fuzzy | unresolved
    needs_review: bool


def load_curated(path: Path = ALIASES) -> dict[str, str]:
    """`"<feed>:<id>" -> canonical id`, maintained by hand."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("players", {})) | dict(data.get("teams", {}))


def resolve(
    feed: str,
    feed_id: str,
    name: str,
    *,
    birth_date: str = "",
    team: str = "",
    candidates: list[Candidate],
    known: dict[str, str] | None = None,
) -> Resolution:
    known = known if known is not None else load_curated()
    alias = known.get(f"{feed}:{feed_id}")
    if alias:
        return Resolution(alias, 1.0, "alias", False)

    norm = normalise_name(name)
    if birth_date:
        for c in candidates:
            if c.birth_date == birth_date and normalise_name(c.name) == norm:
                return Resolution(c.canonical_id, 1.0, "exact", False)

    target = token_sorted(name)
    best: tuple[float, Candidate] | None = None
    for c in candidates:
        if team and c.team and normalise_name(c.team) != normalise_name(team):
            continue  # a similar name at a different club is a different person
        score = jaro_winkler(target, token_sorted(c.name))
        if best is None or score > best[0]:
            best = (score, c)
    if best and best[0] >= FUZZY_THRESHOLD and team:
        return Resolution(best[1].canonical_id, 0.8, "fuzzy", False)
    return Resolution(None, 0.0, "unresolved", True)
