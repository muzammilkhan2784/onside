"""The analytical SQL.

Every query is parameterised - values from a request never get formatted into
SQL text. Column names that vary (the leaderboard metric) come from a fixed
whitelist, never from input.
"""

from __future__ import annotations

from typing import Any

from .duck import query

#: Metrics the leaderboard can rank by, mapped to SQL expressions.
LEADERBOARD_METRICS: dict[str, tuple[str, str]] = {
    "goals": (
        "sum(CASE WHEN type = 'Shot' AND shot_outcome = 'Goal' AND period < 5 THEN 1 ELSE 0 END)",
        "Goals, excluding penalty shootouts",
    ),
    "xg": (
        "round(sum(CASE WHEN type = 'Shot' AND period < 5 THEN shot_xg ELSE 0 END), 2)",
        "Expected goals from every shot taken",
    ),
    "shots": ("sum(CASE WHEN type = 'Shot' AND period < 5 THEN 1 ELSE 0 END)", "Shots"),
    "assists": (
        "sum(CASE WHEN pass_goal_assist THEN 1 ELSE 0 END)",
        "Passes that led directly to a goal",
    ),
    "key_passes": (
        "sum(CASE WHEN pass_shot_assist OR pass_goal_assist THEN 1 ELSE 0 END)",
        "Passes that led directly to a shot",
    ),
    "progressive_passes": (
        "sum(CASE WHEN type = 'Pass' AND pass_outcome = 'Complete' AND end_x IS NOT NULL "
        "AND (sqrt(power(120 - end_x, 2) + power(40 - end_y, 2)) "
        "<= 0.75 * sqrt(power(120 - x, 2) + power(40 - y, 2)) "
        "OR (end_x >= 102 AND end_y BETWEEN 18 AND 62)) THEN 1 ELSE 0 END)",
        "Completed passes that moved the ball at least 25% closer to goal, or into the box",
    ),
    "dribbles": ("sum(CASE WHEN type = 'Dribble' THEN 1 ELSE 0 END)", "Dribbles attempted"),
    "pressures": ("sum(CASE WHEN type = 'Pressure' THEN 1 ELSE 0 END)", "Pressing actions"),
}


def _filters(competition_id: int | None, season_id: int | None) -> tuple[str, list[Any]]:
    where, params = ["player_id IS NOT NULL"], []
    if competition_id is not None:
        where.append("competition_id = ?")
        params.append(competition_id)
    if season_id is not None:
        where.append("season_id = ?")
        params.append(season_id)
    return " AND ".join(where), params


def leaderboard(
    metric: str, *, competition_id: int | None = None, season_id: int | None = None, limit: int = 25
) -> list[dict[str, Any]]:
    if metric not in LEADERBOARD_METRICS:
        raise KeyError(metric)
    expr, _ = LEADERBOARD_METRICS[metric]
    where, params = _filters(competition_id, season_id)
    sql = f"""
        SELECT player_id AS "playerId",
               any_value(player) AS player,
               any_value(team) AS team,
               count(DISTINCT match_id) AS matches,
               {expr} AS value
        FROM events
        WHERE {where}
        GROUP BY player_id
        HAVING value > 0
        ORDER BY value DESC, matches ASC
        LIMIT ?
    """
    return query(sql, [*params, limit])


def player_seasons(player_id: str) -> list[dict[str, Any]]:
    """A player's career, one row per competition-season in the archive."""
    sql = """
        SELECT competition_id AS "competitionId", season_id AS "seasonId",
               any_value(team) AS team,
               count(DISTINCT match_id) AS matches,
               sum(CASE WHEN type = 'Shot' AND shot_outcome = 'Goal' AND period < 5 THEN 1 ELSE 0 END) AS goals,
               round(sum(CASE WHEN type = 'Shot' AND period < 5 THEN shot_xg ELSE 0 END), 2) AS xg,
               sum(CASE WHEN type = 'Shot' AND period < 5 THEN 1 ELSE 0 END) AS shots,
               sum(CASE WHEN pass_goal_assist THEN 1 ELSE 0 END) AS assists,
               sum(CASE WHEN pass_shot_assist OR pass_goal_assist THEN 1 ELSE 0 END) AS "keyPasses",
               sum(CASE WHEN type = 'Pass' THEN 1 ELSE 0 END) AS passes,
               round(avg(CASE WHEN type = 'Pass' THEN (pass_outcome = 'Complete')::INT END), 3) AS "passAccuracy",
               min(match_date) AS first, max(match_date) AS last
        FROM events
        WHERE player_id = ?
        GROUP BY competition_id, season_id
        ORDER BY last DESC
    """
    return query(sql, [player_id])


def player_shots(player_id: str, limit: int = 400) -> list[dict[str, Any]]:
    sql = """
        SELECT match_id AS "matchId", match_date AS date, minute, x, y,
               round(shot_xg, 3) AS xg, shot_outcome AS outcome, shot_type AS type,
               shot_body_part AS "bodyPart"
        FROM events
        WHERE player_id = ? AND type = 'Shot' AND period < 5 AND x IS NOT NULL
        ORDER BY match_date DESC
        LIMIT ?
    """
    return query(sql, [player_id, limit])


def shots(
    *,
    competition_id: int | None = None,
    season_id: int | None = None,
    player_id: str | None = None,
    min_xg: float = 0.0,
    outside_box: bool = False,
    body_part: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Ad-hoc shot query - the kind of question DynamoDB cannot answer."""
    where = ["type = 'Shot'", "period < 5", "coalesce(shot_xg, 0) >= ?"]
    params: list[Any] = [min_xg]
    if competition_id is not None:
        where.append("competition_id = ?")
        params.append(competition_id)
    if season_id is not None:
        where.append("season_id = ?")
        params.append(season_id)
    if player_id:
        where.append("player_id = ?")
        params.append(player_id)
    if outside_box:
        where.append("NOT (x >= 102 AND y BETWEEN 18 AND 62)")
    if body_part:
        where.append("shot_body_part = ?")
        params.append(body_part)
    sql = f"""
        SELECT match_id AS "matchId", match_date AS date, player_id AS "playerId", player, team,
               minute, x, y, round(shot_xg, 3) AS xg, shot_outcome AS outcome,
               shot_type AS type, shot_body_part AS "bodyPart"
        FROM events WHERE {" AND ".join(where)}
        ORDER BY shot_xg DESC NULLS LAST
        LIMIT ?
    """
    return query(sql, [*params, limit])


def players_catalog() -> list[dict[str, Any]]:
    """Every player in the archive with headline career numbers, for the player
    pages and the search index."""
    sql = """
        SELECT player_id AS id, any_value(player) AS name,
               list(DISTINCT team) AS teams,
               count(DISTINCT match_id) AS matches,
               sum(CASE WHEN type = 'Shot' AND shot_outcome = 'Goal' AND period < 5 THEN 1 ELSE 0 END) AS goals,
               round(sum(CASE WHEN type = 'Shot' AND period < 5 THEN shot_xg ELSE 0 END), 2) AS xg,
               sum(CASE WHEN pass_goal_assist THEN 1 ELSE 0 END) AS assists,
               any_value(position) AS position,
               min(match_date) AS first, max(match_date) AS last
        FROM events
        WHERE player_id IS NOT NULL
        GROUP BY player_id
    """
    return query(sql)


def archive_size() -> dict[str, Any]:
    rows = query(
        "SELECT count(*) AS events, count(DISTINCT match_id) AS matches, "
        "count(DISTINCT player_id) AS players FROM events"
    )
    return rows[0] if rows else {"events": 0, "matches": 0, "players": 0}
