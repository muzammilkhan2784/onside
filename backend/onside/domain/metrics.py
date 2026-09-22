"""Derived match metrics.

Every metric here gets a plain-English gloss in `GLOSSARY`, because half of the
people who open a match page do not know what PPDA is, and a number without a
sentence is noise to them. The UI reads the glossary; it does not keep its own.

Pure module. StatsBomb coordinates put the acting team attacking left to right
on a 120 x 80 pitch, so "the final third" is x >= 80 for whichever team is on
the ball - no flipping needed until something is drawn.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from .events import CanonicalEvent, EventType

FINAL_THIRD_X = 80.0
#: PPDA counts pressing in the opponent's 60% of the pitch - for the pressing
#: team that is x >= 48 in its own attacking frame.
PRESSING_ZONE_X = 48.0
ON_TARGET = {"Goal", "Saved", "Saved to Post", "Goal (disallowed)"}

#: A shot worth this much or more is worth a line in the timeline.
BIG_CHANCE_XG = 0.3

#: The standard PPDA denominator: tackles, interceptions, fouls and
#: challenges. Ball recoveries and lost aerial duels are deliberately excluded -
#: counting them roughly halves PPDA and makes every team look like a
#: gegenpressing side.
DEFENSIVE_ACTIONS = {
    EventType.INTERCEPTION.value,
    EventType.FOUL_COMMITTED.value,
    EventType.DRIBBLED_PAST.value,
}


def _is_defensive_action(e: CanonicalEvent) -> bool:
    if e.type == EventType.DUEL.value:
        return e.duel_type == "Tackle"
    return e.type in DEFENSIVE_ACTIONS


GLOSSARY: dict[str, str] = {
    "xg": "Expected goals: how many goals the chances created were worth to an average team. "
    "2.4 means the chances were worth about two or three goals.",
    "possession": "Share of on-ball actions. A rough measure of who had the ball, not who controlled the game.",
    "ppda": "Passes allowed per defensive action in the opponent's half. Lower means more aggressive pressing; "
    "under 9 is intense, over 15 is sitting off.",
    "field_tilt": "Share of all final-third passes that this team made. It shows who was playing in the "
    "other side's half, which possession alone does not.",
    "pass_accuracy": "Completed passes as a share of all passes attempted.",
    "shots_on_target": "Shots that would have gone in without a save - goals plus saves.",
    "progressive_passes": "Passes that moved the ball at least 25% closer to goal, or into the box.",
    "big_chances": "Shots worth 0.3 xG or more - the kind a player is expected to score about one in three of.",
}


@dataclass(frozen=True, slots=True)
class TeamMetrics:
    team_id: str
    team_name: str
    goals: int = 0
    shots: int = 0
    shots_on_target: int = 0
    big_chances: int = 0
    xg: float = 0.0
    passes: int = 0
    passes_completed: int = 0
    progressive_passes: int = 0
    final_third_passes: int = 0
    touches: int = 0
    corners: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    defensive_actions_high: int = 0
    opponent_passes_deep: int = 0
    possession: float = 0.0
    field_tilt: float = 0.0

    @property
    def pass_accuracy(self) -> float:
        return self.passes_completed / self.passes if self.passes else 0.0

    @property
    def ppda(self) -> float | None:
        """None when the team made no defensive actions high up - PPDA is
        undefined then, and printing infinity helps nobody."""
        if not self.defensive_actions_high:
            return None
        return self.opponent_passes_deep / self.defensive_actions_high

    def as_dict(self) -> dict[str, object]:
        return {
            "teamId": self.team_id,
            "team": self.team_name,
            "goals": self.goals,
            "shots": self.shots,
            "shotsOnTarget": self.shots_on_target,
            "bigChances": self.big_chances,
            "xg": round(self.xg, 2),
            "passes": self.passes,
            "passAccuracy": round(self.pass_accuracy, 3),
            "progressivePasses": self.progressive_passes,
            "finalThirdPasses": self.final_third_passes,
            "corners": self.corners,
            "fouls": self.fouls,
            "yellowCards": self.yellow_cards,
            "redCards": self.red_cards,
            "possession": round(self.possession, 3),
            "fieldTilt": round(self.field_tilt, 3),
            "ppda": None if self.ppda is None else round(self.ppda, 2),
        }


def is_progressive(start: tuple[float, float], end: Sequence[float]) -> bool:
    """At least 25% closer to the centre of goal, or ending in the box."""
    if len(end) < 2:
        return False
    goal = (120.0, 40.0)
    d0 = ((goal[0] - start[0]) ** 2 + (goal[1] - start[1]) ** 2) ** 0.5
    d1 = ((goal[0] - end[0]) ** 2 + (goal[1] - end[1]) ** 2) ** 0.5
    in_box = end[0] >= 102.0 and 18.0 <= end[1] <= 62.0
    return in_box or (d0 > 0 and d1 <= 0.75 * d0)


def team_metrics(
    events: Sequence[CanonicalEvent], home_id: str, away_id: str, names: dict[str, str]
) -> tuple[TeamMetrics, TeamMetrics]:
    """Both sides' metrics for one match, regulation and extra time (no shootout)."""
    acc: dict[str, dict[str, float]] = {home_id: defaultdict(float), away_id: defaultdict(float)}

    def other(tid: str) -> str:
        return away_id if tid == home_id else home_id

    for e in events:
        if e.period == 5 or e.team is None or e.team.id not in acc:
            continue
        a = acc[e.team.id]
        a["touches"] += 1
        if e.shot is not None:
            a["shots"] += 1
            a["xg"] += e.shot.xg or 0.0
            if e.shot.outcome in ON_TARGET:
                a["sot"] += 1
            if (e.shot.xg or 0) >= 0.3:
                a["big"] += 1
            if e.shot.is_goal:
                a["goals"] += 1
        if e.type == EventType.OWN_GOAL_AGAINST.value:
            acc[other(e.team.id)]["goals"] += 1
        if e.pass_ is not None:
            a["passes"] += 1
            if e.pass_.complete:
                a["completed"] += 1
            if e.pass_.pass_type == "Corner":
                a["corners"] += 1
            end = e.pass_.end_location
            if e.pass_.complete and len(end) >= 2 and end[0] >= FINAL_THIRD_X:
                a["final_third"] += 1
            if e.pass_.complete and e.location and is_progressive(e.location, end):
                a["progressive"] += 1
            # A pass by this team in its own deep 60% counts against the
            # opponent's pressing.
            if (
                e.location
                and e.location[0] < 72.0
                and e.pass_.pass_type
                not in ("Kick Off", "Goal Kick", "Throw-in", "Corner", "Free Kick")
            ):
                acc[other(e.team.id)]["opp_deep_passes"] += 1
        if _is_defensive_action(e) and e.location and e.location[0] >= PRESSING_ZONE_X:
            a["def_high"] += 1
        if e.type == EventType.FOUL_COMMITTED.value:
            a["fouls"] += 1
        if e.card:
            a["reds" if e.card in ("Red Card", "Second Yellow") else "yellows"] += 1

    h, w = acc[home_id], acc[away_id]
    touches = h["touches"] + w["touches"]
    tilt = h["final_third"] + w["final_third"]

    def build(tid: str, a: dict[str, float], t_share: float, tilt_share: float) -> TeamMetrics:
        return TeamMetrics(
            team_id=tid,
            team_name=names.get(tid, tid),
            goals=int(a["goals"]),
            shots=int(a["shots"]),
            shots_on_target=int(a["sot"]),
            big_chances=int(a["big"]),
            xg=a["xg"],
            passes=int(a["passes"]),
            passes_completed=int(a["completed"]),
            progressive_passes=int(a["progressive"]),
            final_third_passes=int(a["final_third"]),
            touches=int(a["touches"]),
            corners=int(a["corners"]),
            fouls=int(a["fouls"]),
            yellow_cards=int(a["yellows"]),
            red_cards=int(a["reds"]),
            defensive_actions_high=int(a["def_high"]),
            opponent_passes_deep=int(a["opp_deep_passes"]),
            possession=t_share,
            field_tilt=tilt_share,
        )

    hp = h["touches"] / touches if touches else 0.5
    ht = h["final_third"] / tilt if tilt else 0.5
    return build(home_id, h, hp, ht), build(away_id, w, 1 - hp, 1 - ht)


# ---------------------------------------------------------------------------
# pass networks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PassNetwork:
    team_id: str
    nodes: tuple[dict[str, object], ...] = ()
    edges: tuple[dict[str, object], ...] = ()
    until_minute: int = 0
    note: str = ""


def pass_network(
    events: Sequence[CanonicalEvent], team_id: str, *, min_edge: int = 3
) -> PassNetwork:
    """Average positions of the starters and pass volume between pairs.

    Only passes before the team's first substitution count, because after a
    change the eleven on the pitch are no longer the eleven being drawn - and
    averaging positions across two different shapes produces a shape nobody
    actually played.
    """
    first_sub = 10_000
    for e in events:
        if e.team and e.team.id == team_id and e.type == EventType.SUBSTITUTION.value:
            first_sub = min(first_sub, e.minute)

    positions: dict[str, list[tuple[float, float]]] = defaultdict(list)
    names: dict[str, str] = {}
    pairs: dict[tuple[str, str], int] = defaultdict(int)

    for e in events:
        if e.team is None or e.team.id != team_id or e.minute >= first_sub or e.period > 2:
            continue
        if e.pass_ is None or e.player is None or e.location is None:
            continue
        if not e.pass_.complete or e.pass_.recipient is None:
            continue
        positions[e.player.id].append(e.location)
        names[e.player.id] = e.player.name
        end = e.pass_.end_location
        if len(end) >= 2:
            positions[e.pass_.recipient.id].append((end[0], end[1]))
            names.setdefault(e.pass_.recipient.id, e.pass_.recipient.name)
        a, b = sorted((e.player.id, e.pass_.recipient.id))
        pairs[(a, b)] += 1

    nodes = []
    for pid, pts in positions.items():
        if len(pts) < 5:
            continue  # a player barely involved would be placed by noise
        nodes.append(
            {
                "id": pid,
                "name": names.get(pid, pid),
                "x": round(sum(p[0] for p in pts) / len(pts), 1),
                "y": round(sum(p[1] for p in pts) / len(pts), 1),
                "touches": len(pts),
            }
        )
    kept = {n["id"] for n in nodes}
    edges = [
        {"a": a, "b": b, "passes": n}
        for (a, b), n in pairs.items()
        if n >= min_edge and a in kept and b in kept
    ]
    until = first_sub if first_sub < 10_000 else 90
    return PassNetwork(
        team_id=team_id,
        nodes=tuple(sorted(nodes, key=lambda n: -int(n["touches"]))),  # type: ignore[call-overload]
        edges=tuple(sorted(edges, key=lambda e: -int(e["passes"]))),  # type: ignore[call-overload]
        until_minute=until,
        note=f"Completed passes between players who started, up to the first substitution ({until}').",
    )


@dataclass(frozen=True, slots=True)
class TimelineItem:
    kind: str
    period: int
    minute: int
    second: int
    team_id: str
    team: str
    player: str
    detail: str = ""
    event_id: str = ""
    extra: dict[str, object] = field(default_factory=dict)


def timeline(events: Sequence[CanonicalEvent]) -> list[TimelineItem]:
    """The notable events, in match order: goals, cards, substitutions, big
    chances, penalties and the shootout."""
    out: list[TimelineItem] = []
    for e in events:
        if e.team is None:
            continue

        def item(
            kind: str, detail: str = "", xg: float | None = None, ev: CanonicalEvent = e
        ) -> TimelineItem:
            assert ev.team is not None
            return TimelineItem(
                kind=kind,
                period=ev.period,
                minute=ev.minute,
                second=ev.second,
                team_id=ev.team.id,
                team=ev.team.name,
                player=ev.player.name if ev.player else "",
                detail=detail,
                event_id=ev.event_id,
                extra={} if xg is None else {"xg": xg},
            )

        if e.shot is not None:
            if e.period == 5:
                out.append(item("shootout", "scored" if e.shot.is_goal else e.shot.outcome.lower()))
            elif e.shot.is_goal:
                out.append(item("goal", e.shot.shot_type, e.shot.xg))
            elif e.shot.shot_type == "Penalty":
                out.append(item("penalty_miss", e.shot.outcome, e.shot.xg))
            elif (e.shot.xg or 0) >= BIG_CHANCE_XG:
                out.append(item("big_chance", e.shot.outcome, e.shot.xg))
        elif e.type == EventType.OWN_GOAL_AGAINST.value:
            out.append(item("own_goal"))
        if e.card:
            out.append(item("card", e.card))
        if e.type == EventType.SUBSTITUTION.value:
            out.append(
                item("sub", e.substitution_replacement.name if e.substitution_replacement else "")
            )
    return out
