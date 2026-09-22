"""Every key the single-table design uses, in one place.

Access patterns first (SPEC.md section 10.1). Each function here corresponds to
one of them; if a query in the codebase builds a key by hand instead of calling
one of these, that is a bug.

    main table      PK / SK
    GSI1            GSI1PK / GSI1SK   competition-season, date and the news feed
    GSI2            GSI2PK / GSI2SK   team fixtures and story tags

Sort keys that carry numbers are zero-padded, or event 10 sorts before event 2.
"""

from __future__ import annotations


def match_pk(match_id: str) -> str:
    return f"MATCH#{match_id}"


def event_sk(index: int, event_id: str) -> str:
    return f"EVT#{index:06d}#{event_id}"


def correction_sk(decided_at_minute: int, period: int, correction_id: str) -> str:
    return f"CORR#{period}#{decided_at_minute:03d}#{correction_id}"


def team_pk(team_id: str) -> str:
    return f"TEAM#{team_id}"


def player_pk(player_id: str) -> str:
    return f"PLAYER#{player_id}"


def competition_pk(competition_id: str) -> str:
    return f"COMP#{competition_id}"


def comp_season(competition_id: str, season_id: str) -> str:
    return f"COMP#{competition_id}#{season_id}"


def date_pk(date: str) -> str:
    return f"DATE#{date}"


def dated(date: str, match_id: str) -> str:
    """A GSI sort key that orders by date, then match id for stability."""
    mid = f"{int(match_id):010d}" if match_id.isdigit() else match_id
    return f"{date}#{mid}"


def alias_pk(feed: str, feed_id: str) -> str:
    return f"ALIAS#{feed}#{feed_id}"


def tag_pk(tag: str) -> str:
    return f"TAG#{tag}"


FEED_PK = "FEED"
CATALOG_PK = "CATALOG"

# Fixed sort keys
META = "META"
STATE = "STATE"
REPORT = "REPORT"
WPSERIES = "WPSERIES"
SHOTS = "SHOTS"
PASSNET = "PASSNET"
STORY = "STORY"
DAY = "DAY"
TABLE_PREFIX = "TABLE#"
