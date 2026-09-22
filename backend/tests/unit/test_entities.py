from __future__ import annotations

import pytest

from onside.feeds.entities import Candidate, jaro_winkler, normalise_name, resolve

PEOPLE = [
    Candidate("5503", "Lionel Andrés Messi Cuccittini", "1987-06-24", "Barcelona"),
    Candidate("3009", "Kylian Mbappé Lottin", "1998-12-20", "Paris Saint-Germain"),
    Candidate("9999", "Kylian Mbappe", "2001-01-01", "Some Other Club"),
]


def test_names_are_normalised_for_comparison():
    assert normalise_name("Ángel Di María") == "angel di maria"
    assert normalise_name("  N'Golo   Kanté ") == "n golo kante"


@pytest.mark.parametrize(("a", "b", "expected"), [
    ("martha", "marhta", 0.9611), ("dwayne", "duane", 0.84), ("dixon", "dicksonx", 0.8133),
])
def test_jaro_winkler_matches_the_reference_values(a, b, expected):
    assert jaro_winkler(a, b) == pytest.approx(expected, abs=1e-3)


def test_a_curated_alias_wins_outright():
    r = resolve("api-football", "154", "L. Messi", candidates=PEOPLE, known={"api-football:154": "5503"})
    assert (r.canonical_id, r.method, r.confidence) == ("5503", "alias", 1.0)


def test_exact_name_and_birth_date_link_with_full_confidence():
    r = resolve("x", "1", "Lionel Andres Messi Cuccittini", birth_date="1987-06-24", candidates=PEOPLE, known={})
    assert (r.canonical_id, r.method) == ("5503", "exact")


def test_fuzzy_matching_requires_the_same_team():
    same = resolve("x", "2", "Kylian Mbappe Lottin", team="Paris Saint Germain", candidates=PEOPLE, known={})
    assert (same.canonical_id, same.method, same.confidence) == ("3009", "fuzzy", 0.8)
    no_team = resolve("x", "2", "Kylian Mbappe Lottin", candidates=PEOPLE, known={})
    assert no_team.needs_review, "a similar name with no club to confirm it is not a match"


def test_nicknames_fuzzy_matching_cannot_solve_are_flagged_not_guessed():
    r = resolve("x", "3", "Rodri", team="Manchester City", candidates=PEOPLE, known={})
    assert r.canonical_id is None and r.needs_review and r.method == "unresolved"
