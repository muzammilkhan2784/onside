"""The fold: an event log in, a match state out.

    project(log) is deterministic. Same events in, same state out, always -
    however they arrived, however many times they arrived.

That sentence is the whole contract, and `tests/correction/` exists to prove
it. Keep this module pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace

from .corrections import Correction, Supersession, resolve
from .events import CanonicalEvent, EventType, PlayerRef, TeamRef, sorted_canonically

LogRecord = CanonicalEvent | Correction

RED_CARDS = {"Red Card", "Second Yellow"}


@dataclass(frozen=True, slots=True)
class GoalRecord:
    """A goal, including the ones that were taken away again."""

    event_id: str
    period: int
    minute: int
    second: int
    team_id: str
    team_name: str
    scorer: str
    scorer_id: str
    xg: float | None
    shot_type: str
    own_goal: bool = False
    # Correction state - a disallowed goal stays in the record, flagged.
    disallowed: bool = False
    correction_reason: str = ""
    correction_authority: str = ""
    corrected_at_minute: int | None = None
    synthesised_correction: bool = False

    @property
    def counts(self) -> bool:
        return not self.disallowed


@dataclass(frozen=True, slots=True)
class CardRecord:
    event_id: str
    period: int
    minute: int
    team_id: str
    player: str
    card: str

    @property
    def is_red(self) -> bool:
        return self.card in RED_CARDS


@dataclass(frozen=True, slots=True)
class TeamStats:
    shots: int = 0
    on_target: int = 0
    xg: float = 0.0
    passes: int = 0
    passes_completed: int = 0
    final_third_passes: int = 0
    defensive_actions_opp_half: int = 0
    corners: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_cards: int = 0

    @property
    def pass_accuracy(self) -> float:
        return self.passes_completed / self.passes if self.passes else 0.0


@dataclass(frozen=True, slots=True)
class MatchState:
    """Everything the fold knows. Rebuilt from scratch on every correction."""

    match_id: str
    home: TeamRef | None = None
    away: TeamRef | None = None
    period: int = 0
    minute: int = 0
    second: int = 0
    status: str = "scheduled"  # scheduled | live | half_time | finished
    goals: tuple[GoalRecord, ...] = ()
    cards: tuple[CardRecord, ...] = ()
    home_stats: TeamStats = field(default_factory=TeamStats)
    away_stats: TeamStats = field(default_factory=TeamStats)
    shootout: tuple[tuple[str, bool], ...] = ()  # (team_id, scored)
    superseded: tuple[str, ...] = ()
    corrections: tuple[Correction, ...] = ()
    possession_home: float = 0.5
    version: int = 0

    # ---- score ---------------------------------------------------------
    @property
    def home_score(self) -> int:
        return sum(1 for g in self.goals if g.counts and g.team_id == self._home_id)

    @property
    def away_score(self) -> int:
        return sum(1 for g in self.goals if g.counts and g.team_id == self._away_id)

    @property
    def _home_id(self) -> str:
        return self.home.id if self.home else ""

    @property
    def _away_id(self) -> str:
        return self.away.id if self.away else ""

    @property
    def score(self) -> tuple[int, int]:
        return self.home_score, self.away_score

    @property
    def shootout_score(self) -> tuple[int, int]:
        h = sum(1 for tid, ok in self.shootout if tid == self._home_id and ok)
        a = sum(1 for tid, ok in self.shootout if tid == self._away_id and ok)
        return h, a

    @property
    def red_cards(self) -> tuple[int, int]:
        h = sum(1 for c in self.cards if c.is_red and c.team_id == self._home_id)
        a = sum(1 for c in self.cards if c.is_red and c.team_id == self._away_id)
        return h, a

    @property
    def scoreline(self) -> str:
        h, a = self.score
        base = f"{h}-{a}"
        sh, sa = self.shootout_score
        if sh or sa:
            base += f" ({sh}-{sa} on penalties)"
        return base

    @property
    def disallowed_goals(self) -> tuple[GoalRecord, ...]:
        return tuple(g for g in self.goals if g.disallowed)

    def clock(self) -> str:
        """Human match clock. Period 5 is the shootout, which has no clock."""
        if self.period == 5:
            return "PENS"
        return f"{self.minute}'"


# ---------------------------------------------------------------------------
# the fold
# ---------------------------------------------------------------------------


def _effective(event: CanonicalEvent, sup: Supersession | None) -> CanonicalEvent:
    """Apply any `amend`/`reassign` payload to a copy of the event.

    The stored event is never mutated - this returns the view the projection
    should use. Only whitelisted fields can be amended; a feed cannot invent a
    new field through a correction payload.
    """
    if sup is None or not sup.amendments:
        return event
    a = sup.amendments
    out = event
    if "player" in a:
        p = a["player"]
        out = replace(
            out,
            player=p if isinstance(p, PlayerRef) else PlayerRef(str(p["id"]), str(p["name"])),
        )
    if "team" in a:
        t = a["team"]
        out = replace(
            out,
            team=t if isinstance(t, TeamRef) else TeamRef(str(t["id"]), str(t["name"])),
        )
    if "minute" in a:
        out = replace(out, minute=int(a["minute"]))
    if "xg" in a and out.shot is not None:
        out = replace(out, shot=replace(out.shot, xg=float(a["xg"])))
    return out


def _stats(acc: dict[str, float]) -> TeamStats:
    """The accumulator carries floats because xG is one; everything else is a
    count and is narrowed back here rather than at every increment."""
    return TeamStats(
        shots=int(acc["shots"]),
        on_target=int(acc["on_target"]),
        xg=float(acc["xg"]),
        passes=int(acc["passes"]),
        passes_completed=int(acc["passes_completed"]),
        final_third_passes=int(acc["final_third_passes"]),
        defensive_actions_opp_half=int(acc["defensive_actions_opp_half"]),
        corners=int(acc["corners"]),
        fouls=int(acc["fouls"]),
        yellow_cards=int(acc["yellow_cards"]),
        red_cards=int(acc["red_cards"]),
    )


def _split(log: Iterable[LogRecord]) -> tuple[list[CanonicalEvent], list[Correction]]:
    events: list[CanonicalEvent] = []
    corrections: list[Correction] = []
    seen_events: set[str] = set()
    for rec in log:
        if isinstance(rec, Correction):
            corrections.append(rec)
        else:
            # Appending the same event id twice is a no-op. The store enforces
            # this with a conditional write; the fold enforces it again so the
            # projection is right even if the store is ever bypassed.
            if rec.event_id in seen_events:
                continue
            seen_events.add(rec.event_id)
            events.append(rec)
    return events, corrections


def project(log: Sequence[LogRecord], match_id: str = "") -> MatchState:
    """Fold an append-only log into the current match state.

    Pure and total: any sequence of records projects to something, and the
    result depends only on the *set* of records, never on their arrival order.
    """
    events, corrections = _split(log)
    sup_by_event = resolve(corrections)
    ordered = sorted_canonically(events)

    if not match_id:
        match_id = ordered[0].match_id if ordered else ""

    home: TeamRef | None = None
    away: TeamRef | None = None
    # Starting XI events name the two teams in a stable order; fall back to
    # first-seen order so a partial log still projects.
    for e in ordered:
        if e.type == EventType.STARTING_XI.value and e.team:
            if home is None:
                home = e.team
            elif e.team.id != home.id and away is None:
                away = e.team
    if home is None or away is None:
        for e in ordered:
            if e.team is None:
                continue
            if home is None:
                home = e.team
            elif e.team.id != home.id and away is None:
                away = e.team
            if home and away:
                break

    goals: list[GoalRecord] = []
    cards: list[CardRecord] = []
    shootout: list[tuple[str, bool]] = []
    hs = {
        "shots": 0,
        "on_target": 0,
        "xg": 0.0,
        "passes": 0,
        "passes_completed": 0,
        "final_third_passes": 0,
        "defensive_actions_opp_half": 0,
        "corners": 0,
        "fouls": 0,
        "yellow_cards": 0,
        "red_cards": 0,
    }
    as_ = dict(hs)
    possession_touches = [0, 0]

    period = ordered[0].period if ordered else 0
    minute = second = 0
    status = "scheduled" if not ordered else "live"

    on_target = {"Goal", "Saved", "Saved to Post"}
    defensive = {
        EventType.PRESSURE.value,
        EventType.INTERCEPTION.value,
        EventType.CLEARANCE.value,
        EventType.BLOCK.value,
        EventType.DUEL.value,
        EventType.FOUL_COMMITTED.value,
        EventType.BALL_RECOVERY.value,
    }

    for ev in ordered:
        sup = sup_by_event.get(ev.event_id)
        e = _effective(ev, sup)
        period, minute, second = e.period, e.minute, e.second

        is_home = home is not None and e.team is not None and e.team.id == home.id
        bucket = hs if is_home else as_

        if e.team is not None:
            possession_touches[0 if is_home else 1] += 1

        if e.type == EventType.HALF_END.value and e.period == 1:
            status = "half_time"
        elif e.type == EventType.HALF_START.value:
            status = "live"

        # ---- shots and goals ----
        if e.shot is not None:
            if e.period == 5:  # the shootout is not part of the scoreline
                if e.team is not None:
                    shootout.append((e.team.id, e.shot.is_goal))
                continue
            bucket["shots"] += 1
            bucket["xg"] += e.shot.xg or 0.0
            if e.shot.outcome in on_target:
                bucket["on_target"] += 1
            if e.shot.is_goal and e.team is not None:
                goals.append(
                    GoalRecord(
                        event_id=e.event_id,
                        period=e.period,
                        minute=e.minute,
                        second=e.second,
                        team_id=e.team.id,
                        team_name=e.team.name,
                        scorer=e.player.name if e.player else "Unknown",
                        scorer_id=e.player.id if e.player else "",
                        xg=e.shot.xg,
                        shot_type=e.shot.shot_type,
                        disallowed=bool(sup and sup.disallowed),
                        correction_reason=sup.reason if sup else "",
                        correction_authority=sup.authority if sup else "",
                        corrected_at_minute=sup.decided_at_minute if sup else None,
                        synthesised_correction=bool(sup and sup.synthesised),
                    )
                )

        # An own goal credits the *other* team. StatsBomb emits
        # "Own Goal Against" for the conceding side.
        if e.type == EventType.OWN_GOAL_AGAINST.value and e.team is not None and home and away:
            credited = away if e.team.id == home.id else home
            goals.append(
                GoalRecord(
                    event_id=e.event_id,
                    period=e.period,
                    minute=e.minute,
                    second=e.second,
                    team_id=credited.id,
                    team_name=credited.name,
                    scorer=e.player.name if e.player else "Own goal",
                    scorer_id=e.player.id if e.player else "",
                    xg=None,
                    shot_type="Own Goal",
                    own_goal=True,
                    disallowed=bool(sup and sup.disallowed),
                    correction_reason=sup.reason if sup else "",
                    correction_authority=sup.authority if sup else "",
                    corrected_at_minute=sup.decided_at_minute if sup else None,
                    synthesised_correction=bool(sup and sup.synthesised),
                )
            )

        # ---- cards ----
        if e.card and e.team is not None and not (sup and sup.disallowed):
            cards.append(
                CardRecord(
                    event_id=e.event_id,
                    period=e.period,
                    minute=e.minute,
                    team_id=e.team.id,
                    player=e.player.name if e.player else "",
                    card=e.card,
                )
            )
            bucket["red_cards" if e.card in RED_CARDS else "yellow_cards"] += 1

        # ---- passing / pressing ----
        if e.pass_ is not None:
            bucket["passes"] += 1
            if e.pass_.complete:
                bucket["passes_completed"] += 1
            if e.pass_.pass_type == "Corner":
                bucket["corners"] += 1
            end = e.pass_.end_location
            if len(end) >= 1 and end[0] >= 80.0:
                bucket["final_third_passes"] += 1
        if e.type == EventType.FOUL_COMMITTED.value:
            bucket["fouls"] += 1
        if e.type in defensive and e.location and e.location[0] >= 48.0:
            bucket["defensive_actions_opp_half"] += 1

    total_touches = possession_touches[0] + possession_touches[1]
    poss_home = possession_touches[0] / total_touches if total_touches else 0.5

    if ordered and ordered[-1].type == EventType.HALF_END.value and period >= 2:
        status = "finished"

    return MatchState(
        match_id=match_id,
        home=home,
        away=away,
        period=period,
        minute=minute,
        second=second,
        status=status,
        goals=tuple(goals),
        cards=tuple(cards),
        home_stats=_stats(hs),
        away_stats=_stats(as_),
        shootout=tuple(shootout),
        superseded=tuple(sorted(k for k, v in sup_by_event.items() if v.disallowed)),
        corrections=tuple(sorted(corrections, key=lambda c: c.sort_key)),
        possession_home=poss_home,
        version=len(events) + len(corrections),
    )


def project_until(log: Sequence[LogRecord], period: int, minute: int) -> MatchState:
    """The state as it stood at a moment in the match.

    This is what lets Onside answer "was this ever 2-1?" - the question no
    mutable-row scores site can answer at all.
    """
    cutoff = (period, minute)
    kept: list[LogRecord] = []
    for rec in log:
        if isinstance(rec, Correction):
            if (rec.period, rec.decided_at_minute) <= cutoff:
                kept.append(rec)
        elif (rec.period, rec.minute) <= cutoff:
            kept.append(rec)
    return project(kept)


#: The outcome a disallowed goal carries in `effective_events`. The shot still
#: happened - its xG and its place on the shot map are real - but it did not
#: count, so `ShotDetail.is_goal` is False for it.
DISALLOWED_GOAL = "Goal (disallowed)"


def effective_events(log: Sequence[LogRecord]) -> list[CanonicalEvent]:
    """The events as the corrections say they should now be read.

    Amendments and reassignments are applied, and a disallowed goal keeps its
    shot but loses its goal. Everything downstream that reads events rather
    than the projected state - the win-probability features, the metrics -
    goes through this, so a correction moves every number, not only the score.
    """
    events, corrections = _split(log)
    sup = resolve(corrections)
    out: list[CanonicalEvent] = []
    for e in sorted_canonically(events):
        s = sup.get(e.event_id)
        eff = _effective(e, s)
        if s is not None and s.disallowed and eff.shot is not None and eff.shot.is_goal:
            eff = replace(eff, shot=replace(eff.shot, outcome=DISALLOWED_GOAL))
        out.append(eff)
    return out
