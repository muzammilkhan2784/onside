# Attribution

## StatsBomb Open Data

Onside is built on [StatsBomb Open Data](https://github.com/statsbomb/open-data),
made freely available by StatsBomb for research and education.

All event data in this repository — 13,911,986 events across 3,961 matches, 24
competitions and 80 seasons, with expected goals and 360° freeze-frames — comes
from that dataset. The 2022 World Cup final used in the demo is match
`3869685`.

Per StatsBomb's licence, public analysis built on the open data must credit
them. That credit appears here, in the README, in the footer of every page of
the web app, in the footer of the standalone demo, and in the `source` field of
every event the API serves.

> Data provided by StatsBomb.

Onside is an independent portfolio project. It is not affiliated with, endorsed
by, or connected to StatsBomb in any way.

## What is *not* StatsBomb data

**The VAR corrections in replays are synthesised by Onside.** StatsBomb's open
data does not record VAR decisions. Because correction handling is the point of
this project, `backend/onside/replay/var_injector.py` generates realistic
corrections deterministically from the real event stream so the pipeline can be
demonstrated.

Every synthesised correction carries `synthesised=True` through the entire
system and is labelled as synthesised everywhere it is displayed — the
timeline, the banner, the report, the API and the replay controls. No viewer
should ever mistake one for a historical fact.

Real feeds deliver corrections natively. `ApiFootballAdapter` maps API-Football's
`Var` → "Goal cancelled" events into genuine, non-synthesised corrections; that
path is covered by the contract tests.

## Other feeds

- **football-data.org** — when an API key is configured, the Matches page and
  the home page show their fixtures, results, tables, scorers and in-play
  scores, credited wherever they appear ("Real fixtures from football-data.org"). The competition list in
  `backend/tests/contract/fixtures/football_data_competitions.recorded.json` is a
  genuine recording of their unauthenticated `/v4/competitions` endpoint;
  `football_data_matches.schema-shaped.json` is shaped from their published
  schema and says so. Used under their free-tier terms for non-commercial use.
- **API-Football** — no data from this provider is included. The fixture used in
  tests is shaped from their published response schema and is labelled as such
  in its own `_provenance` field.

## Social posts

The Buzz dashboard shows public posts from Bluesky, Mastodon and Reddit's
r/soccer (and X when configured). Reddit posts come from the subreddit's
public feed and are shown as their titles, with the linked article. Every post is shown with its author's name and handle and a
link to the original, as text, unedited. Onside keeps a post for three days and
only what it displays. It skips posts marked sensitive, replies, and anything
from authors who opted out of being shown to logged-out viewers (Bluesky's
`!no-unauthenticated` label) or out of search indexing (Mastodon's `noindex`).
The posts belong to their authors.

## Crests

Onside holds no licence for club or national-team badges, so none are used.
Every crest on the site is generated: a shield in colours derived from the
team's name, with its initials. They are not, and do not imitate, any club's
real badge.

## Libraries

FastAPI, Uvicorn, Pydantic, boto3, redis-py, DuckDB, PyArrow, LightGBM,
scikit-learn, NumPy, httpx, defusedxml, pytest, Hypothesis, moto, fakeredis,
the AWS CDK and the AWS Lambda Web Adapter, React,
Vite, Tailwind CSS, TanStack Query, Recharts, Vitest and Testing Library, each
under its own licence.

Fonts on the web app are self-hosted from the @fontsource packages (SIL Open
Font License); the standalone demo loads them from Google Fonts: Anton, Manrope
and JetBrains Mono.
