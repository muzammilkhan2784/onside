"""The phrase bank.

Why templates and not an LLM: every sentence here is generated from the
model's own numbers by rules that were written down, so the report is
explainable line by line, costs nothing per match, cannot hallucinate a goal
that did not happen, and regenerates automatically when a correction lands.
An LLM layer could sit on top. The point is that the system does not need one.
"""

from __future__ import annotations

from ..events import PITCH_LENGTH
from .selector import Moment

# ---------------------------------------------------------------------------
# verb phrases, keyed by what the data says about the shot
# ---------------------------------------------------------------------------


def verb_phrase(moment: Moment, distance: float | None = None) -> str:
    """How the goal was scored, in words, decided only by the event fields."""
    if moment.shot_type == "Own Goal":
        return "turned it into his own net"
    if moment.shot_type == "Penalty":
        return "converted the penalty"
    if distance is not None and distance >= 25:
        return "struck one from distance"
    if moment.xg is not None and moment.xg >= 0.4:
        return "finished from close range"
    if moment.xg is not None and moment.xg <= 0.06:
        return "scored from almost nothing"
    if moment.shot_type == "Free Kick":
        return "curled in the free kick"
    return "found the net"


def distance_from_goal(location: tuple[float, float] | None) -> float | None:
    """Metres from the centre of the goal, on StatsBomb's 120x80 pitch."""
    if location is None:
        return None
    dx = PITCH_LENGTH - location[0]
    dy = location[1] - 40.0
    return float((dx * dx + dy * dy) ** 0.5)


# ---------------------------------------------------------------------------
# swing clauses
# ---------------------------------------------------------------------------


def swing_clause(moment: Moment, winner_idx: int, winner_name: str) -> str:
    """Attach the probability move, but only when it is worth a sentence."""
    before = moment.wp_before[winner_idx] * 100
    after = moment.wp_after[winner_idx] * 100
    if abs(after - before) < 3:
        return ""
    return f"That moved {winner_name} from {before:.0f}% to {after:.0f}% to win."


def moment_sentence(
    moment: Moment, winner_idx: int, winner_name: str, distance: float | None = None
) -> str:
    """One line of the report."""
    minute = f"{moment.minute}'"
    score = f"{moment.score_after[0]}-{moment.score_after[1]}"
    swing = swing_clause(moment, winner_idx, winner_name)

    if moment.kind == "goal":
        head = f"{minute} - {moment.player} {verb_phrase(moment, distance)} to make it {score}."
    elif moment.kind == "disallowed_goal":
        ruled = f" at {moment.ruled_out_at}'" if moment.ruled_out_at else ""
        head = (
            f"{minute} - {moment.player} put the ball in the net for {moment.team_name}, "
            f"but it was ruled out{ruled}: {moment.detail.lower()}. The score stayed {score}."
        )
        swing = ""  # a disallowed goal did not move the real probability
    elif moment.kind == "red_card":
        card = "a second yellow" if moment.detail == "Second Yellow" else "a straight red"
        head = f"{minute} - {moment.player} was sent off for {moment.team_name}, {card}."
    elif moment.kind == "penalty_miss":
        outcome = "saved" if "Saved" in moment.detail else "missed"
        head = f"{minute} - {moment.player} {outcome} a penalty for {moment.team_name}."
    elif moment.kind == "big_chance":
        xg = f"{moment.xg:.2f}" if moment.xg is not None else "?"
        outcome = {
            "Saved": "was denied by the keeper",
            "Off T": "dragged it wide",
            "Post": "hit the woodwork",
            "Blocked": "saw the shot blocked",
        }.get(moment.detail, "went close")
        head = (
            f"{minute} - {moment.player} {outcome} from a chance worth {xg} "
            f"expected goals - the best {moment.team_name} had created."
        )
    else:
        head = f"{minute} - {moment.detail}"

    return f"{head} {swing}".strip()


# ---------------------------------------------------------------------------
# ledes, chosen from the shape of the final state
# ---------------------------------------------------------------------------

LEDE_COMFORTABLE = "{winner} won {score} and were rarely troubled."
LEDE_NARROW = "{winner} won it {score}, and it was as tight as that scoreline suggests."
LEDE_COMEBACK = "{winner} came from behind to win {score}, having trailed for {trailing} minutes."
LEDE_LATE = (
    "{winner} left it late, scoring the decisive goal in the last ten minutes of a {score} win."
)
LEDE_DRAW = "{home} and {away} shared {score}, and neither will be certain they should have."
LEDE_SHOOTOUT = "{winner} won it on penalties after {score} over 120 minutes, a match that swung further than the score alone shows."
LEDE_GOALLESS = "{home} and {away} finished goalless, a match decided by the chances neither took."


def closing_line(biggest: Moment | None, winner_name: str) -> str:
    if biggest is None:
        return ""
    pct = abs(biggest.wp_after[0] - biggest.wp_before[0]) * 100
    if pct < 3:
        return ""
    return (
        f"The single biggest swing of the match came in the {biggest.minute}th minute, "
        f"worth {pct:.0f} percentage points."
    )


EXTRA_TIME_NOTE = (
    "Win probability is shown for the 90 minutes the model is trained on. "
    "Extra time and penalties are outside its range, where a draw stops meaning "
    "anything, so no figure is quoted for those moments rather than an invented one."
)

CORRECTION_NOTE = "This report was regenerated after a correction was applied to the match log."

SYNTHESISED_NOTE = (
    "Note: the VAR correction in this match is synthesised by Onside for demonstration. "
    "StatsBomb open data does not include VAR decisions."
)
