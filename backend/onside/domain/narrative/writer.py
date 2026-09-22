"""Compose the match report from selected moments.

`write()` is a pure function of (state, events, win-probability series). That
is what makes the report regenerate for free when a correction lands: the
correction changes the state and the series, and the same function run again
produces the corrected report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..events import CanonicalEvent
from ..match_state import MatchState
from . import templates as T
from .selector import Moment, biggest_swing, select


@dataclass(frozen=True, slots=True)
class MatchReport:
    headline: str
    lede: str
    moments: tuple[Moment, ...]
    lines: tuple[str, ...]
    closing: str
    notes: tuple[str, ...]

    def as_text(self) -> str:
        parts = [self.headline, "", self.lede, ""]
        parts += list(self.lines)
        if self.closing:
            parts += ["", self.closing]
        if self.notes:
            parts += [""] + [f"({n})" for n in self.notes]
        return "\n".join(parts)


def _winner(state: MatchState) -> tuple[int, str]:
    """Index into (home, draw, away) and the name to use in prose."""
    h, a = state.score
    home_name = state.home.name if state.home else "The home side"
    away_name = state.away.name if state.away else "The away side"
    if state.shootout:
        sh, sa = state.shootout_score
        if sh > sa:
            return 0, home_name
        if sa > sh:
            return 2, away_name
    if h > a:
        return 0, home_name
    if a > h:
        return 2, state.away.name if state.away else "The away side"
    return 1, state.home.name if state.home else "Both sides"


def _lede(state: MatchState, moments: Sequence[Moment], winner_name: str) -> str:
    h, a = state.score
    home = state.home.name if state.home else "Home"
    away = state.away.name if state.away else "Away"
    score = f"{h}-{a}"

    if state.shootout:
        return T.LEDE_SHOOTOUT.format(winner=winner_name, score=score)
    if h == a == 0:
        return T.LEDE_GOALLESS.format(home=home, away=away)
    if h == a:
        return T.LEDE_DRAW.format(home=home, away=away, score=score)

    winner_is_home = h > a
    home_id = state.home.id if state.home else ""
    goals = sorted(
        (g for g in state.goals if g.counts and g.period <= 4),
        key=lambda g: (g.period, g.minute, g.second),
    )

    # Walk the running score: how long did the winner trail, and when did they
    # go ahead for good?
    run_h = run_a = 0
    trailing_since: int | None = None
    trailed_minutes = 0
    decisive_minute = 0
    for g in goals:
        if g.team_id == home_id:
            run_h += 1
        else:
            run_a += 1
        diff = (run_h - run_a) if winner_is_home else (run_a - run_h)
        if diff < 0 and trailing_since is None:
            trailing_since = g.minute
        elif diff >= 0 and trailing_since is not None:
            trailed_minutes += g.minute - trailing_since
            trailing_since = None
        if diff == 1 and ((g.team_id == home_id) == winner_is_home):
            decisive_minute = g.minute  # the goal that put them ahead for the last time

    margin = abs(h - a)
    if trailed_minutes:
        return T.LEDE_COMEBACK.format(winner=winner_name, score=score, trailing=trailed_minutes)
    if margin >= 3:
        return T.LEDE_COMFORTABLE.format(winner=winner_name, score=score)
    if decisive_minute >= 80:
        return T.LEDE_LATE.format(winner=winner_name, score=score)
    if margin == 2:
        return T.LEDE_COMFORTABLE.format(winner=winner_name, score=score)
    return T.LEDE_NARROW.format(winner=winner_name, score=score)


def format_date(iso: str) -> str:
    """2022-12-18 -> 18 December 2022. Leaves anything unparseable alone."""
    import datetime as _dt

    try:
        d = _dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%B')} {d.year}"


def write(
    state: MatchState,
    events: Sequence[CanonicalEvent],
    wp_series: Sequence[Mapping[str, float]],
    *,
    competition: str = "",
    date: str = "",
) -> MatchReport:
    """Generate the report. Deterministic: same inputs, same prose."""
    moments = select(state, events, wp_series)
    winner_idx, winner_name = _winner(state)

    locations = {e.event_id: e.location for e in events}
    lines = tuple(
        T.moment_sentence(
            m,
            winner_idx,
            winner_name,
            distance=T.distance_from_goal(locations.get(m.event_id)),
        )
        for m in moments
    )

    home = state.home.name if state.home else "Home"
    away = state.away.name if state.away else "Away"
    suffix = f" - {competition}" if competition else ""
    suffix += f", {format_date(date)}" if date else ""
    headline = f"{home} {state.scoreline.split(' (')[0]} {away}{suffix}"
    if state.shootout:
        sh, sa = state.shootout_score
        headline = f"{home} {state.score[0]}-{state.score[1]} {away} ({winner_name} win {sh}-{sa} on penalties){suffix}"

    notes: list[str] = []
    if any(m.period >= 3 for m in moments):
        notes.append(T.EXTRA_TIME_NOTE)
    if state.corrections:
        notes.append(T.CORRECTION_NOTE)
    if any(c.synthesised for c in state.corrections):
        notes.append(T.SYNTHESISED_NOTE)

    return MatchReport(
        headline=headline,
        lede=_lede(state, moments, winner_name),
        moments=tuple(moments),
        lines=lines,
        closing=T.closing_line(biggest_swing(moments), winner_name),
        notes=tuple(notes),
    )
