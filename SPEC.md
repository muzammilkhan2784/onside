# Onside — Build Specification

**Correction-aware live soccer intelligence: every match, every event, and an explanation of what actually decided it**

> *Renamed from Byline to Onside on 2026-09-20. Original tagline: a byline is where the cross comes from, and the credit on a match report. This
> project is both: the deepest event data, turned into the story of the game.*

This document is the complete build spec. It is written to be handed to a fresh
Claude Code session with no prior context.

---

## 0. Quick orientation for the building session

You are building a soccer match platform that does three things no existing site
does together:

1. **Never lies about the score.** VAR disallows goals, scorers get reassigned,
   xG gets revised. Onside keeps an append-only event log where corrections are
   first-class events, so the timeline shows *"Goal 62' — disallowed by VAR at
   64', offside in the build-up"* instead of silently mutating.
2. **Tells you what happened.** Auto-generated match report built by ranking
   every moment by how much it swung win probability. No LLM, no wire copy — the
   narrative falls out of the model.
3. **Goes to the finest grain that exists.** Every pass, shot, carry, duel and
   pressure with pitch coordinates; shot freeze-frames showing where all 22
   players stood.

- **Author:** Muzammilkhan Pathan — MS Computer Science, NYU
- **Purpose:** portfolio project for Summer 2027 SWE internship applications
- **Timeline:** 6 weeks part-time
- **Companion project:** Faultline (Neo4j static analysis). Onside shares no
  technology with it.

**This replaces the StatStream fantasy-football spec.** That spec still exists at
`Industry/statstream/SPEC.md` if it is ever wanted.

**Read §3 (what makes this hard) and §6 (scope) before writing any code.** A
soccer scores site built naively is a CRUD app, and there are twenty of them in
every applicant pool. The three things in §3 are what stop that happening. If
they get cut, the project is not worth building.

---

## 1. Audience — read before designing any screen

This is a hiring showcase. The people who open it are recruiters, hiring managers
and engineers. Some follow soccer; many do not. They will spend ninety seconds.

- **Nothing is ever a blank screen.** Every empty state says, in plain English,
  what would be here and what to do next.
- **A first-time visitor must see the product working in ten seconds.** No
  signup, no waiting for a real match. The landing page opens a replayed World
  Cup final already in progress (§19).
- **Never show soccer jargon without a gloss.** "xG 2.4" means nothing to half
  your audience. Show *"xG 2.4 — the chances they created were worth about 2.4
  goals to an average team."*
- **Never show a raw error.** "Something went wrong" is also banned. Say what
  happened and what to do.
- **Odd states get explained.** A 0-0 at minute 3 is not a bug. Say *"No goals
  yet — this feed is live and updates as the match plays."*

Write the copy as you build each screen. Retrofitting never happens.

---

## 2. The gap — what existing sites do, and what none of them do

You asked what is missing from the soccer sites that already exist. This section
is the product thesis, and an edited version of it belongs at the top of the
README.

| Site | What it's best at | What it doesn't do |
|---|---|---|
| **FlashScore** | Fastest updates, widest competition coverage | Almost no depth; corrections happen silently |
| **Sofascore** | Deepest live stats, heat maps, attack momentum | No calibrated win probability; no correction history |
| **FotMob** | Best live UI, xG, player ratings | No audit trail; no synthesised explanation of the match |
| **FBref / StatsBomb** | Deepest historical analytics | Not live; no narrative |
| **Understat** | Good public xG models | Few leagues; not live |
| **ESPN / OneFootball** | News and editorial | Shallow statistics |
| **WhoScored** | Ratings and detailed stats | Slow; no live explanation |

**Six cross-cutting gaps that none of them fill:**

1. **Corrections are invisible.** VAR overturns a goal and the score silently
   changes. Nobody shows *what* was corrected, *when*, or *why*. This is the
   single biggest data-integrity problem in live soccer and no consumer product
   treats it as one.
2. **"I missed the game" is unsolved.** Highlights are video and rights-locked.
   Text recaps are either generic wire copy or a stat dump. Nobody ranks the
   moments that actually decided the match and explains them in order.
3. **Calibrated live win probability is rare in soccer.** It is standard in the
   NFL and NBA. Sofascore's "attack momentum" is a proxy, not a probability, and
   nobody publishes a calibration curve or a Brier score.
4. **No data provenance.** Two sites report different xG for the same shot and
   neither says which model or which feed. Users cannot tell who to trust.
5. **Nothing is fast or accessible.** Every major soccer site is heavy,
   ad-saturated and hostile on a slow connection. A text-first, screen-reader
   friendly, sub-100KB live page does not exist.
6. **No developer-grade free API.** The good feeds cost €99–249/month. There is
   no clean, documented, open API over deep event data.

**Onside's thesis:** not another scores site. A match-intelligence platform that
is *correct under correction*, *explains itself*, and *exposes everything through
one fast documented API*.

---

## 3. What makes this hard

Be explicit about this, because a scores site is otherwise a CRUD app. These five
are the engineering content of the project:

1. **Event sourcing with retroactive correction.** The match state is a fold over
   an append-only log. A VAR overturn appends a correction event that supersedes
   an earlier one; the projection is rebuilt and every consumer is notified of a
   *diff*, not a new snapshot. Getting this right — and provably right, via
   replay tests — is the backbone.
2. **Multi-feed reconciliation and entity resolution.** The same player has a
   different id in StatsBomb, football-data.org and API-Football. Feeds disagree
   and arrive out of order. You need an adapter layer, a canonical entity store,
   and a documented conflict policy.
3. **A calibrated win-probability model that runs in under 5ms.** Trained on real
   historical match states, evaluated with a Brier score and a reliability
   diagram. This is genuine ML with a measurable, publishable result — not a
   model bolted on for decoration.
4. **Narrative synthesis without an LLM.** Rank moments by |Δ win probability|,
   select, order, and template into prose. Defensible in an interview line by
   line, because you wrote every rule.
5. **Live table recomputation under competition-specific tie-break rules.** La
   Liga breaks ties on head-to-head *before* goal difference; the Premier League
   does the opposite. Encoding six competitions' rules correctly is fiddly domain
   logic and perfect for table-driven tests.

---

## 4. Data sources — the honest constraint

You said "every soccer game in the world." That is not achievable on free data,
and pretending otherwise would be the one thing that undermines the project.
Here is the real picture, and the design that makes it a strength.

### 4.1 What's actually available

| Source | Cost | Coverage | Depth | Live? |
|---|---|---|---|---|
| **StatsBomb Open Data** | Free | 27 competitions, 95 competition-seasons | **Elite** — every event with x/y, xG, 360 freeze-frames | No (historical) |
| **football-data.org** | Free tier | 12 competitions | Fixtures, results, tables, scorers | Delayed |
| **API-Football** | Free 100 req/day; ~$19/mo | 1,200+ leagues | Events, lineups, stats, 15s updates | Yes |
| **openfootball** | Free | Wide | Fixtures only | No |

StatsBomb's free set includes the 2022 World Cup, Euro 2024, Copa América 2024,
Women's World Cup 2023, Euro 2025 (women's), every Messi La Liga season, and
Champions League finals back to 1970 — roughly **3,400 matches at ~3,000 events
each, about 10 million events.** That is the same granularity professional clubs
buy.

**Licence:** free to use; any published analysis must credit StatsBomb and use
their logo from the media pack. Put the attribution in the README and in the app
footer. Do this from day one.

### 4.2 The design that makes the constraint a feature

Build a **feed adapter layer** (§12). Three adapters ship:

| Adapter | Role |
|---|---|
| `StatsBombAdapter` | Deep historical events → the replay engine → **the demo and the benchmarks** |
| `FootballDataAdapter` | Real fixtures, results and tables for 12 live competitions |
| `ApiFootballAdapter` | Written and tested against recorded fixtures; **enabled by config, not deployed** |

The README says plainly: *"Global live coverage requires a paid feed. Onside is
feed-agnostic; the API-Football adapter is implemented and tested, and enabling
it is a config change and a $19/month subscription. The demo runs on StatsBomb
open data, which is deeper than any paid live feed."*

That is a better answer than fake coverage, and "I designed for a feed I chose
not to pay for, and here is the adapter and its contract tests" is a strong
interview moment.

---

## 5. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | |
| API | FastAPI 0.115+ | Async, native WebSockets, free OpenAPI |
| Validation | Pydantic v2 | |
| Event log + live state | **DynamoDB** | Append-only log, conditional writes, single-digit-ms projections |
| Deep archive | **S3 + Parquet + DuckDB** | 10M events; DuckDB queries columnar Parquet in-process, no cluster |
| Queue | **Redis Streams** | Consumer groups, reclaimable work |
| Live tables | **Redis sorted sets** | |
| WS backplane | **Redis pub/sub** | |
| ML | scikit-learn + LightGBM | Win probability; small, explainable, fast |
| Frontend | React 18 + TypeScript 5 | |
| Build | Vite 5 | |
| Pitch graphics | **Hand-rolled SVG** | Shot maps, pass networks, freeze-frames. No chart lib fits a pitch. |
| Timeline charts | Recharts | Win-probability curve, xG race |
| Data fetching | TanStack Query v5 | |
| Styling | Tailwind 3 | |
| IaC | **AWS CDK (Python)** | Stays in Python |
| Compute | ECS Fargate | |
| Lint / types | Ruff, mypy `--strict` | From commit one |
| Tests | pytest, pytest-asyncio | |
| Local | Docker Compose | Redis, DynamoDB Local, MinIO (S3), API, workers, frontend |
| CI | GitHub Actions | |

**Deliberately not used:** PostgreSQL, Kafka, Neo4j, MongoDB, Flask — all
allocated to other projects in this portfolio.

---

## 6. Scope

### In scope

- Feed adapter layer with three adapters and contract tests
- Append-only event store with corrections and supersession
- Projection engine rebuilding match state from the log
- Live ingest via Redis Streams with reclaimable workers
- WebSocket push with Redis pub/sub backplane and resumable subscriptions
- Win-probability model: training pipeline, calibration report, <5ms inference
- Automatic match report generated from win-probability swings
- Live league tables with per-competition tie-break rules
- Deep match page: timeline, shot map, pass network, freeze-frames, xG race
- Player and team pages with career/season aggregates from DuckDB
- Replay engine driving live simulation from StatsBomb data
- Public documented REST API + OpenAPI
- Accessible, low-bandwidth match page (< 100KB, works without JS for core score)
- AWS deploy via CDK; benchmarks; CI

### Explicitly OUT of scope

- ❌ Video, highlights, or any broadcast rights content
- ❌ User accounts, following, notifications *(v1 has no auth at all — it is a
  public read-only product; this removes a week of work and adds nothing)*
- ❌ Betting odds, tips, or anything gambling-adjacent
- ❌ Transfer news, editorial, or scraped articles
- ❌ Fantasy scoring
- ❌ Live commentary text from third parties
- ❌ Sports other than soccer
- ❌ Mobile apps
- ❌ Scraping any site that forbids it — StatsBomb, football-data.org and
  API-Football are all used within their published terms
- ❌ LLM-generated narrative *(the template engine is the point — see §14)*

---

## 7. Repository layout

```
onside/
├── README.md
├── SPEC.md
├── LICENSE
├── ATTRIBUTION.md                       # StatsBomb credit + logo
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile                           # multi-stage: base/api/worker/dev
├── Makefile
├── .env.example
├── .github/workflows/ci.yml
│
├── backend/
│   ├── onside/
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── ids.py
│   │   │
│   │   ├── domain/                      # pure logic, zero I/O
│   │   │   ├── events.py                # the canonical event taxonomy (§8)
│   │   │   ├── match_state.py           # the fold: events -> MatchState
│   │   │   ├── corrections.py           # supersession rules (§9)
│   │   │   ├── tables.py                # standings + tie-break strategies (§15)
│   │   │   ├── metrics.py               # xG agg, xT, PPDA, field tilt
│   │   │   └── narrative/
│   │   │       ├── selector.py          # rank moments by |ΔWP|
│   │   │       ├── templates.py         # phrase bank
│   │   │       └── writer.py            # compose the report
│   │   │
│   │   ├── feeds/
│   │   │   ├── base.py                  # FeedAdapter protocol
│   │   │   ├── statsbomb.py
│   │   │   ├── football_data.py
│   │   │   ├── api_football.py
│   │   │   ├── normalise.py             # feed event -> canonical event
│   │   │   └── entities.py              # cross-feed entity resolution (§12.3)
│   │   │
│   │   ├── store/
│   │   │   ├── client.py
│   │   │   ├── keys.py
│   │   │   ├── schema.py
│   │   │   ├── event_log.py             # append-only writes
│   │   │   ├── projections.py           # match state, tables, player agg
│   │   │   └── catalog.py               # competitions, teams, players
│   │   │
│   │   ├── archive/
│   │   │   ├── writer.py                # events -> Parquet -> S3
│   │   │   ├── duck.py                  # DuckDB session over S3 Parquet
│   │   │   └── queries.py               # analytical SQL
│   │   │
│   │   ├── streams/
│   │   │   ├── client.py
│   │   │   ├── producer.py
│   │   │   ├── consumer.py
│   │   │   ├── pubsub.py
│   │   │   └── tables_cache.py
│   │   │
│   │   ├── models/
│   │   │   ├── features.py              # match-state -> feature vector
│   │   │   ├── train_wp.py              # training pipeline
│   │   │   ├── evaluate_wp.py           # Brier, log loss, reliability diagram
│   │   │   └── predict.py               # <5ms inference wrapper
│   │   │
│   │   ├── workers/
│   │   │   ├── ingest_worker.py         # stream -> event log -> projection
│   │   │   ├── projector.py             # rebuild projections on correction
│   │   │   ├── reclaimer.py             # XAUTOCLAIM
│   │   │   └── archiver.py              # finished matches -> Parquet
│   │   │
│   │   ├── api/
│   │   │   ├── main.py
│   │   │   ├── deps.py
│   │   │   ├── schemas.py
│   │   │   ├── errors.py
│   │   │   ├── ws/{manager.py,gateway.py}
│   │   │   └── routes/
│   │   │       ├── competitions.py
│   │   │       ├── matches.py
│   │   │       ├── events.py
│   │   │       ├── report.py
│   │   │       ├── tables.py
│   │   │       ├── players.py
│   │   │       ├── teams.py
│   │   │       ├── analytics.py
│   │   │       ├── replay.py
│   │   │       └── health.py
│   │   │
│   │   └── replay/
│   │       ├── download.py              # StatsBomb open-data fetch + cache
│   │       ├── build_timeline.py        # events -> ordered wall-clock feed
│   │       ├── var_injector.py          # synthesise realistic corrections
│   │       └── driver.py                # replay at N× speed
│   │
│   ├── tests/
│   │   ├── unit/                        # domain, tables, narrative, features
│   │   ├── integration/                 # store, streams, api, ws
│   │   ├── correction/                  # the signature suite (§20.3)
│   │   ├── contract/                    # feed adapter conformance
│   │   └── model/                       # calibration gate
│   │
│   ├── benchmarks/
│   └── scripts/
│
├── infra/                               # CDK Python
│   ├── app.py
│   └── stacks/{network,data,compute}_stack.py
│
└── frontend/
    └── src/
        ├── pages/{Landing,Match,Competition,Team,Player,ReplayAdmin}.tsx
        ├── components/
        │   ├── Timeline.tsx             # with correction markers
        │   ├── WinProbabilityChart.tsx
        │   ├── MatchReport.tsx
        │   ├── Pitch.tsx                # base SVG pitch, 120x80
        │   ├── ShotMap.tsx
        │   ├── PassNetwork.tsx
        │   ├── FreezeFrame.tsx          # the 360 shot snapshot
        │   ├── XgRace.tsx
        │   ├── LeagueTable.tsx
        │   ├── CorrectionBadge.tsx
        │   ├── EmptyState.tsx
        │   └── ConnectionBadge.tsx
        └── ws/useLiveMatch.ts
```

---

## 8. The soccer domain at finest grain

### 8.1 Canonical event taxonomy

Onside's internal event model follows StatsBomb's, because it is the most
complete public taxonomy. Other feeds normalise *into* it (§12.2).

**Every event carries:**

| Field | Type | Notes |
|---|---|---|
| `event_id` | UUID | Stable across corrections |
| `match_id` | string | |
| `index` | int | Order within the match |
| `period` | int | 1, 2, 3, 4 (ET), 5 (penalties) |
| `timestamp` | string | `HH:MM:SS.mmm` within the period |
| `minute`, `second` | int | |
| `type` | enum | See the list below |
| `possession` | int | Possession-chain id |
| `possession_team` | team | |
| `play_pattern` | enum | Regular Play, From Corner, From Free Kick, From Throw In, From Counter, From Goal Kick, From Keeper, From Kick Off, Other |
| `team`, `player`, `position` | ref | |
| `location` | `[x, y]` | Pitch is **120 × 80**, origin top-left, attacking left→right |
| `duration` | float | seconds |
| `under_pressure` | bool | |
| `counterpress` | bool | |
| `out`, `off_camera` | bool | |
| `related_events` | list[UUID] | |

**Event types:** `50/50`, `Bad Behaviour`, `Ball Receipt`, `Ball Recovery`,
`Block`, `Carry`, `Clearance`, `Dispossessed`, `Dribble`, `Dribbled Past`,
`Duel`, `Error`, `Foul Committed`, `Foul Won`, `Goal Keeper`, `Half End`,
`Half Start`, `Injury Stoppage`, `Interception`, `Miscontrol`, `Offside`,
`Own Goal Against`, `Own Goal For`, `Pass`, `Player Off`, `Player On`,
`Pressure`, `Referee Ball-Drop`, `Shield`, `Shot`, `Starting XI`,
`Substitution`, `Tactical Shift`.

**Pass-specific:** `recipient`, `length`, `angle`, `height` (Ground/Low/High),
`end_location`, `body_part`, `type` (Corner / Free Kick / Goal Kick /
Interception / Kick Off / Recovery / Throw-in), `outcome` (Incomplete / Out /
Pass Offside / Injury Clearance / Unknown), `technique` (Inswinging /
Outswinging / Straight / Through Ball), and the booleans `cross`, `cut_back`,
`switch`, `through_ball`, `deflected`, `miscommunication`, `shot_assist`,
`goal_assist`.

**Shot-specific:** `statsbomb_xg`, `end_location` (3D — includes height, so you
know if it went over the bar), `key_pass_id`, `body_part` (Right Foot / Left
Foot / Head / Other), `type` (Open Play / Free Kick / Penalty / Corner /
Kick Off), `outcome` (Blocked / Goal / Off T / Post / Saved / Saved Off T /
Saved to Post / Wayward), `technique` (Backheel / Diving Header / Half Volley /
Lob / Normal / Overhead Kick / Volley), and `first_time`, `follows_dribble`,
`redirect`, `one_on_one`, `open_goal`, `deflected`, `aerial_won`, plus
**`freeze_frame`** — the position of every visible player at the moment of the
shot, each flagged teammate/opponent and keeper/not.

**Goalkeeper-specific:** `type` (Shot Saved / Collected / Punch / Smother /
Save / Claim / Keeper Sweeper / Penalty Saved), `outcome`, `position`,
`technique`, `body_part`, `end_location`.

**Substitution:** `replacement`, `outcome` (Tactical / Injury).
**Bad Behaviour / Foul Committed:** `card` (Yellow / Second Yellow / Red),
`penalty`, `advantage`, `offensive`.
**Tactical Shift:** the full new `tactics.lineup` with formation and positions.

### 8.2 Match-level facts

Competition, season, matchday, stage, venue, attendance, kickoff UTC, status,
home/away team, score, half-time score, aggregate score and leg (for two-legged
ties), penalty shootout result, referee and assistants, VAR official, weather,
and both managers.

### 8.3 Derived metrics to compute

| Metric | Definition |
|---|---|
| **xG** (per shot, cumulative) | From the feed; never recompute — attribute the source |
| **xA** | xG of the shot a pass assisted |
| **xT (expected threat)** | Value of moving the ball into a pitch zone; 16×12 grid, computed from the archive |
| **PPDA** | Opponent passes ÷ own defensive actions in their 60% of the pitch — a pressing intensity measure |
| **Field tilt** | Share of final-third passes |
| **Progressive pass / carry** | Advances ≥25% closer to goal, or into the box |
| **Possession chain** | Events grouped by `possession` id; chains ending in a shot |
| **Pass network** | Nodes = average position of each starter; edges = pass volume between pairs |
| **Packing** | Defenders taken out of the game by a pass |
| **Win probability** | §13 |

Each derived metric gets a plain-English gloss in the UI (§1).

---

## 9. Event sourcing and corrections — the backbone

### 9.1 The rule

**The event log is append-only. Nothing is ever updated or deleted.**

Match state is a pure fold:

```python
def project(events: Sequence[CanonicalEvent]) -> MatchState:
    """Deterministic. Same events in, same state out, always."""
```

A correction is a new record:

```python
class Correction(BaseModel):
    correction_id: str
    match_id: str
    supersedes: str            # the event_id being corrected
    kind: Literal["disallow", "reassign", "amend", "reinstate"]
    reason: str                # "Offside in the build-up"
    authority: Literal["VAR", "referee", "feed_correction", "official_review"]
    decided_at_minute: int     # when the decision was made
    payload: dict              # the replacement values, for reassign/amend
    received_at: float
```

The projector applies events in `index` order, and when it encounters a
correction it marks the superseded event accordingly:

| `kind` | Effect on the projection |
|---|---|
| `disallow` | The superseded event stops counting (goal removed from the score) but stays visible in the timeline, struck through, with the reason |
| `reassign` | Attribution changes (different scorer, or goal → own goal); the score is unchanged |
| `amend` | A field changes (xG revised, minute corrected) |
| `reinstate` | A previous `disallow` is itself reversed |

### 9.2 Why this matters, and why it is the project's differentiator

Every other site mutates. Onside can answer questions no other site can:

- *"Was this ever 2-1?"* → yes, between 62' and 64'
- *"Which of tonight's goals were checked by VAR?"*
- *"How often does this referee's team have a goal overturned?"*
- *"What was the win probability during the four minutes the goal stood?"*

The UI shows corrections as first-class content: a struck-through timeline entry
with a `CorrectionBadge`, and on the win-probability chart a shaded band over the
minutes the disallowed goal was live, labelled *"score was 2-1 here before VAR."*

### 9.3 Correction propagation

When a correction lands, downstream state must change consistently:

```
correction appended
      │
      ▼
 rebuild MatchState from the log        (pure, fast: ~3,000 events ≈ 8ms)
      │
      ├── diff against the previous projection
      ├── write the new projection (conditional on version)
      ├── recompute win probability for every minute from the correction onward
      ├── invalidate + recompute the league table if the result changed
      ├── regenerate the match report
      └── publish a `correction` message with the diff, not a snapshot
```

**Publish the diff.** Clients render the change (*"Goal disallowed — score is now
1-1"*) rather than silently swapping numbers. That is the whole point.

### 9.4 Idempotency and ordering

- Every event has a stable `event_id`; appending the same id twice is a no-op
  (`ConditionExpression: attribute_not_exists(SK)`)
- Feeds deliver out of order — the log stores arrival order, the projector sorts
  by `(period, timestamp, index)`
- Projections carry a `version`; writes are conditional on the expected version,
  so two projectors racing cannot interleave

---

## 10. DynamoDB design

One table, `onside`, two GSIs, on-demand billing.

### 10.1 Access patterns first

| # | Pattern | Index | Key |
|---|---|---|---|
| 1 | Append an event | main | `PK=MATCH#<mid>, SK=EVT#<idx:06d>#<event_id>` |
| 2 | Read a match's full event log in order | main | `PK=MATCH#<mid>, SK begins_with EVT#` |
| 3 | Read current match state | main | `PK=MATCH#<mid>, SK=STATE` |
| 4 | Read the match report | main | `PK=MATCH#<mid>, SK=REPORT` |
| 5 | Read the WP series | main | `PK=MATCH#<mid>, SK=WPSERIES` |
| 6 | List corrections for a match | main | `PK=MATCH#<mid>, SK begins_with CORR#` |
| 7 | Today's / a date's matches | GSI1 | `GSI1PK=DATE#<yyyy-mm-dd>` |
| 8 | A competition's matches in a season | GSI1 | `GSI1PK=COMP#<cid>#<season>` |
| 9 | A team's matches | GSI2 | `GSI2PK=TEAM#<tid>` |
| 10 | Current league table | main | `PK=COMP#<cid>#<season>, SK=TABLE` |
| 11 | Team / player / competition catalog | main | `PK=TEAM#<tid> \| PLAYER#<pid> \| COMP#<cid>, SK=META` |
| 12 | Entity alias lookup (feed id → canonical) | main | `PK=ALIAS#<feed>#<feed_id>, SK=ENTITY` |

### 10.2 Item shapes

| Entity | PK | SK | Notes |
|---|---|---|---|
| Event | `MATCH#<mid>` | `EVT#<idx:06d>#<eid>` | full canonical event; **zero-pad the index** or 10 sorts before 2 |
| Correction | `MATCH#<mid>` | `CORR#<ts>#<cid>` | `supersedes`, `kind`, `reason`, `authority` |
| Match state | `MATCH#<mid>` | `STATE` | score, status, cards, lineups, `version`, `superseded_ids` |
| Match meta | `MATCH#<mid>` | `META` | `GSI1PK=DATE#…`, `GSI2PK=TEAM#…`, competition, venue, referee |
| WP series | `MATCH#<mid>` | `WPSERIES` | array of `{minute, p_home, p_draw, p_away}` |
| Report | `MATCH#<mid>` | `REPORT` | generated narrative + selected moments |
| Table | `COMP#<cid>#<season>` | `TABLE` | rows + the tie-break rule id used |
| Catalog | `TEAM#<tid>` / `PLAYER#<pid>` / `COMP#<cid>` | `META` | |
| Alias | `ALIAS#<feed>#<feed_id>` | `ENTITY` | `entity_type`, `canonical_id`, `confidence` |

> A finished match with 3,000 events is ~3,000 items. At 3,400 replayed matches
> that is ~10M items — fine for DynamoDB on-demand, but **archive finished
> matches to Parquet and delete the raw events** after archiving (§11). Keep
> `STATE`, `REPORT`, `WPSERIES` and `META` in DynamoDB forever; they are small.

---

## 11. The deep archive: S3 + Parquet + DuckDB

DynamoDB is wrong for *"every shot Messi took from outside the box in La Liga,
grouped by season."* That is an analytical scan.

**Design:** when a match finishes and is archived, write its events as Parquet to

```
s3://onside-archive/events/competition_id=<cid>/season=<season>/match_id=<mid>.parquet
```

Hive-style partitioning lets DuckDB prune whole directories.

```python
con.execute("""
    INSTALL httpfs; LOAD httpfs;
    SELECT player_name,
           count(*)                AS shots,
           round(sum(shot_xg), 2)  AS total_xg,
           sum(CASE WHEN shot_outcome = 'Goal' THEN 1 ELSE 0 END) AS goals
    FROM read_parquet('s3://onside-archive/events/competition_id=11/season=*/*.parquet',
                      hive_partitioning = true)
    WHERE type = 'Shot' AND location_x < 102        -- outside the box
    GROUP BY 1 ORDER BY total_xg DESC LIMIT 20
""")
```

Locally, MinIO stands in for S3 so the same code path runs in Docker Compose.

**Why DuckDB rather than Athena or Spark:** it runs in-process, costs nothing,
needs no cluster, and 10M rows of Parquet is far below where it struggles. Say
this in the README — choosing the smallest tool that fits is an engineering
signal, and "why not Spark" is a question you want asked.

**Benchmark it** (§21): the same aggregate over 10M events in DuckDB vs. a
DynamoDB scan. The gap will be two orders of magnitude and it justifies the split
architecture in one line.

---

## 12. Feed adapters

### 12.1 The protocol

```python
class FeedAdapter(Protocol):
    name: str

    async def list_competitions(self) -> list[CompetitionRef]: ...
    async def list_matches(self, competition_id: str, season: str) -> list[MatchRef]: ...
    async def fetch_match(self, match_id: str) -> RawMatch: ...
    async def stream_events(self, match_id: str) -> AsyncIterator[RawEvent]: ...
    def normalise(self, raw: RawEvent) -> CanonicalEvent | Correction: ...
    def capabilities(self) -> FeedCapabilities: ...
```

`FeedCapabilities` declares what the feed actually provides — `has_events`,
`has_xg`, `has_freeze_frames`, `has_lineups`, `is_live`, `update_seconds`. The UI
reads it and degrades honestly: *"This competition's feed provides scores and
lineups but not shot-level data."* Never show an empty shot map with no
explanation (§1).

### 12.2 Normalisation

Every adapter maps its feed's vocabulary into the §8 taxonomy. Where a feed is
shallower, the canonical event is created with the fields it has and the rest
absent — **never invented**. Each event records `source_feed` and `source_event_id`
so provenance survives (gap #4 in §2).

### 12.3 Entity resolution

The same player is `statsbomb:5503`, `football-data:44`, `api-football:154`.

**Resolution pipeline:**
1. Exact match on a known alias (`ALIAS#<feed>#<id>`) → done
2. Exact match on normalised name + birth date → link, confidence 1.0
3. Fuzzy name (token-sorted Jaro-Winkler ≥ 0.92) + same team + same season →
   link, confidence 0.8
4. Otherwise create a new canonical entity flagged `needs_review`

Normalise names properly: strip diacritics, fold case, handle "Rodri" vs
"Rodrigo Hernández Cascante" via an explicit alias table for known cases. Ship a
small hand-curated alias file — pretending fuzzy matching solves this is worse
than admitting it doesn't.

**Expose `/api/entities/unresolved`** and show the count on the admin page. An
honest accounting of what the system could not resolve is more impressive than a
silent wrong join.

### 12.4 Conflict policy

When two feeds disagree about the same fact, a documented precedence applies:

| Fact | Precedence |
|---|---|
| Score / result | official feed > StatsBomb > others |
| Event detail (x/y, xG) | StatsBomb (only source with it) |
| Lineups | most recently updated |
| Kickoff time | official feed |

Conflicts are **logged and counted**, never silently resolved. Surface the count.

---

## 13. Win probability

### 13.1 Features

Computed from match state at each minute:

| Feature | Notes |
|---|---|
| `minute` | 0–90+ |
| `score_diff` | home − away |
| `red_card_diff` | home − away |
| `xg_diff` | cumulative |
| `shots_diff`, `shots_on_target_diff` | |
| `is_neutral_venue` | matters for tournaments |
| `pre_match_elo_diff` | Elo computed from match history in the archive |
| `minutes_remaining` | including estimated stoppage |
| `possession_diff` | rolling 10-minute window |

Target: three classes — home win, draw, away win. Label from the final result.

### 13.2 Training

Training rows = one per (match, minute). StatsBomb's ~3,400 matches × ~95
minutes ≈ **320,000 rows.** Plenty.

- Split by **match**, never by row, or the same match leaks across the split
- Split by **season** for the test set — a time-based split is the honest one
- Baseline: multinomial logistic regression
- Main: LightGBM, shallow (`num_leaves=31`, `max_depth=6`), early stopping

### 13.3 Evaluation — this is the part that matters

Report and publish:

- **Multiclass Brier score** vs. two baselines: a constant prior, and the
  bookmaker-free "current score decides it" rule
- **Log loss**
- **Reliability diagram** — bin predictions into deciles, plot predicted vs.
  observed frequency. This chart goes in the README.
- **Calibration by minute bucket** — models are usually well-calibrated at 80'
  and badly at 10'; show it rather than hiding it

**CI gate:** `tests/model/test_calibration.py` fails the build if the Brier score
on the held-out season regresses beyond a stored threshold. That is the same
trick as Faultline's accuracy gate and it is what makes this real engineering
rather than a notebook.

### 13.4 Inference

Model serialised to `models/wp_lgbm.txt`, loaded once at process start.
Prediction must be **under 5ms** — assert it in a test. Recomputing an entire
match's 95-minute series after a correction must be under 200ms.

---

## 14. The match report — narrative without an LLM

This is what answers *"a game happened yesterday, tell me what happened."*

### 14.1 Moment selection

```
1. Compute the WP series for the match
2. For each event, delta = |WP_after - WP_before| for the eventual winner's class
3. Always include: all goals, all red cards, all penalties (given or missed),
   all corrections, and the final whistle
4. Add the highest-delta remaining moments until the report has 6-8 moments
5. Suppress near-duplicates within 90 seconds of each other, keeping the larger
6. Order chronologically
```

### 14.2 Templating

`templates.py` is a phrase bank keyed by `(event_type, context)`. Context
includes: was it the lead-changer, the equaliser, in stoppage time, against the
run of play (shot xG low but scored), and did it follow a correction.

```
"{minute}' — {scorer} {verb_phrase} to make it {score}. {swing_clause}"

verb_phrase:   "finished from close range"        (xG > 0.4)
               "struck one from distance"          (distance > 25m)
               "converted the penalty"             (type == Penalty)
               "headed in from the corner"         (body_part Head, from corner)

swing_clause:  "That moved {team} from {before}% to {after}% to win."
```

Then a lede generated from the final state (comfortable win / narrow win /
comeback / late drama), and a closing line naming the biggest single swing.

Example output:

> **Argentina 3–3 France (Argentina win 4–2 on penalties) — World Cup Final, 18 December 2022**
>
> Argentina led for most of it, France twice dragged it back, and it took
> penalties to settle a final that swung more than any in recent memory.
>
> **23'** — Messi converted the penalty to make it 1–0. That moved Argentina from 41% to 63% to win.
> **36'** — Di María finished from close range to make it 2–0. Argentina now 84%.
> **80'** — Mbappé converted the penalty to make it 2–1. France up from 6% to 17%.
> **81'** — Mbappé struck again to make it 2–2 — the biggest single swing of the match, France from 17% to 48%.
> …

### 14.3 Why templates, not an LLM

Say this plainly in the README: the report is generated from the model's own
numbers by rules you wrote, so every sentence is explainable and reproducible,
it costs nothing per match, it cannot hallucinate a goal that did not happen, and
it regenerates automatically when a correction lands. An LLM layer could be added
on top; the point is that the system does not need one.

---

## 15. League tables and tie-breaks

Tables are a fold over finished matches, and **the tie-break rules differ by
competition** — this is the fiddly domain logic that makes for good tests.

| Competition | Order after points |
|---|---|
| Premier League | GD → GF → head-to-head → play-off |
| **La Liga** | **head-to-head points → head-to-head GD** → overall GD → GF |
| Serie A | head-to-head → GD → GF |
| Bundesliga | GD → GF → head-to-head |
| Ligue 1 | GD → GF |
| UCL group stage | h2h points → h2h GD → h2h away goals → GD → GF → away goals |

Implement as a strategy registry:

```python
TIE_BREAKS: dict[str, list[TieBreakRule]] = {
    "PL":  [GoalDifference(), GoalsFor(), HeadToHead()],
    "LIGA":[HeadToHeadPoints(), HeadToHeadGD(), GoalDifference(), GoalsFor()],
    ...
}
```

Head-to-head rules need the mini-table among only the tied teams, which is
recursive when three or more teams are level. **Write the three-way-tie test.**
Store the rule id used on the table item so the UI can say *"La Liga separates
level teams on head-to-head record first."*

---

## 16. Realtime

Same pattern as any multi-instance WebSocket system, and the README should
explain it:

```
ingest worker  →  PUBLISH match:<mid>  {diff}
                        │
         ┌──────────────┼──────────────┐
      API task A     API task B     API task C
      (subscribed)   (subscribed)   (subscribed)
```

**Channels:** `match:<mid>` (events, corrections, state diffs, WP updates),
`comp:<cid>` (table changes, other scores), `system`.

**Requirements:**
- Subscribe to a Redis channel only while a local client needs it
- Every message carries a per-channel `seq`; mirror the last 1,000 into
  `chanlog:<channel>` so a reconnecting client can resume with `?since=`
- Server ping every 20s; ALB idle timeout set to 300s
- Drop a client whose send queue exceeds 100 messages; it reconnects and resumes
- No sticky sessions — the backplane removes the need

**Message types:** `event_appended`, `correction_applied` (carries the diff),
`state_changed`, `wp_updated`, `report_regenerated`, `table_changed`.

---

## 17. API

Public, read-only, no auth. `/docs` is part of the product (gap #6 in §2).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/competitions` | All competitions with their feed capabilities |
| `GET` | `/api/competitions/{cid}/seasons` | |
| `GET` | `/api/competitions/{cid}/table?season=` | Live table + the tie-break rule applied |
| `GET` | `/api/matches?date=` | Matches on a date, all competitions |
| `GET` | `/api/matches/{mid}` | State: score, status, lineups, cards |
| `GET` | `/api/matches/{mid}/events` | Full event log; filters `type`, `player`, `period`, `min_xg` |
| `GET` | `/api/matches/{mid}/corrections` | **Every correction with reason and authority** |
| `GET` | `/api/matches/{mid}/timeline` | Display timeline, corrections marked |
| `GET` | `/api/matches/{mid}/report` | **The generated match report** |
| `GET` | `/api/matches/{mid}/win-probability` | Per-minute series |
| `GET` | `/api/matches/{mid}/shots` | Shots with xG and freeze-frames |
| `GET` | `/api/matches/{mid}/pass-network?team=` | Nodes and edges |
| `GET` | `/api/matches/{mid}/stats` | Both teams: possession, PPDA, field tilt, xG |
| `GET` | `/api/teams/{tid}` / `/matches` / `/form` | |
| `GET` | `/api/players/{pid}` / `/seasons` | Career aggregates (DuckDB) |
| `GET` | `/api/analytics/shots` | Ad-hoc shot query: competition, season, player, zone |
| `GET` | `/api/analytics/leaderboard` | xG, xA, progressive carries — by competition/season |
| `GET` | `/api/entities/unresolved` | Entity-resolution honesty endpoint |
| `POST` | `/api/replay/start` | `{match_id, speed, inject_var}` |
| `POST` | `/api/replay/pause` / `/resume` / `/stop` | |
| `GET` | `/api/replay/status` | |
| `WS` | `/ws/match/{mid}?since=` | |
| `WS` | `/ws/competition/{cid}?since=` | |
| `GET` | `/health`, `/metrics` | |

**Error envelope** — `error` for the frontend to branch on, `message` written for
a human, always:

```json
{
  "error": "feed_lacks_capability",
  "message": "This competition's feed provides scores and lineups, but not shot-level data, so there's no shot map for this match.",
  "detail": {"capability": "has_events", "feed": "football-data"}
}
```

---

## 18. Frontend

### 18.1 Pages

| Page | Contents |
|---|---|
| **Landing** | One-line explanation, a replayed match live right now, today's matches |
| **Match** | The centrepiece — see below |
| **Competition** | Table (with the tie-break explanation), fixtures, results |
| **Team** | Squad, form, results, aggregate stats |
| **Player** | Career and season aggregates, shot map, xG/xA trend |
| **Replay admin** | Start/pause/speed, and the VAR injector toggle |

### 18.2 The match page

Tabs: **Summary · Timeline · Stats · Shots · Passing · Report**

- **Summary** — score, scorers, cards, the win-probability chart with any
  correction bands shaded, and the top three moments from the report
- **Timeline** — every notable event in order. **Corrections rendered inline,
  struck through, with the reason and the authority.** This is the screenshot for
  the README.
- **Stats** — possession, shots, xG, PPDA, field tilt, each with a plain-English
  gloss on hover
- **Shots** — SVG pitch with shots sized by xG and coloured by outcome; click a
  shot to open its **freeze-frame** showing all 22 positions at that instant
- **Passing** — pass network per team; average positions, edge width by volume
- **Report** — the generated narrative (§14)

### 18.3 Pitch rendering

`Pitch.tsx` draws a 120×80 SVG pitch with correct markings (18-yard box 44 wide ×
18 deep, 6-yard box 20 × 6, centre circle radius 10, penalty spot 12 from goal).
Everything else composes on top of it. Get the geometry right once; every other
visual depends on it.

Coordinate transform: StatsBomb x∈[0,120], y∈[0,80] with y increasing downward —
matching SVG. Flip for the away team so both attack the same way when comparing.

### 18.4 Low-bandwidth mode

One of the six gaps is that every soccer site is heavy. Deliver on it:

- The match page's core score, scorers and timeline render **server-side as HTML**
  at `/m/{match_id}` — no JavaScript needed
- Under 100KB total for that route; assert it in a test
- Full interactive app progressively enhances from there
- Proper semantics: `<time>`, `<table>` for the table, ARIA live region for score
  updates so screen readers announce goals

Put the byte count in the README next to a competitor's. It is a concrete,
checkable claim.

### 18.5 Empty and odd states

| State | Copy |
|---|---|
| Match hasn't kicked off | *"Kick-off is at 20:00. The timeline fills in live as the match plays."* |
| 0-0 at 12' | *"No goals yet. Chances created so far are worth about 0.3 goals."* |
| Feed lacks events | *"This competition's feed gives scores and lineups but not shot-level data."* |
| Correction applied | *"Goal disallowed — VAR ruled offside in the build-up. The score is now 1–1."* |
| WS reconnecting | *"Reconnecting — showing the last score we received."* |
| No matches today | *"No matches today in the competitions we cover. Here's yesterday's."* |
| Unresolved entity | *"We couldn't confidently match this player across feeds, so some stats may be incomplete."* |

---

## 19. Replay engine

The demo, the test harness and the benchmark driver, all in one. Build it in
week 2.

### 19.1 Data

```python
# backend/onside/replay/download.py
# Clones/pulls github.com/statsbomb/open-data, caches JSON locally, gitignored.
```

3,400 matches. Cache the parsed events as Parquet on first load; JSON parsing
10M events repeatedly is wasteful.

### 19.2 Wall-clock timeline

Events carry period timestamps. `build_timeline.py` converts them into a schedule
of `(offset_seconds, event)` so the driver can emit them at a real or
accelerated pace.

### 19.3 The VAR injector — important

StatsBomb open data does **not** contain VAR overturns as such. Since corrections
are the project's differentiator, they must be demonstrable:

`var_injector.py` deterministically synthesises realistic corrections from the
real event stream:

- Pick a goal; 2–4 minutes later emit a `disallow` correction citing offside,
  handball, or a foul in the build-up
- Occasionally emit a `reassign` (deflection makes it an own goal)
- Occasionally emit an `amend` (xG revised)
- Seeded by `match_id`, so the same match always produces the same corrections —
  demos and tests are reproducible

**Label it honestly everywhere.** The replay admin page and the README say:
*"StatsBomb open data doesn't include VAR decisions, so Onside synthesises
realistic corrections from the real event stream to demonstrate the correction
pipeline. Real feeds deliver these natively — see the adapter."* Never let a
viewer think a synthesised correction is a historical fact.

### 19.4 Driver

```
python -m onside.replay.driver --match 3869685 --speed 30 --inject-var
python -m onside.replay.driver --competition 43 --season 2022 --speed max   # load mode
```

Progress in plain English: *"Replaying Argentina v France at 30× — 1,840 of 3,612
events sent, about 50 seconds remaining."*

---

## 20. Testing

Target **85% coverage on `backend/onside/`**, enforced.

### 20.1 Unit — the pure domain

- `project()` is deterministic: same events → identical state, 100 random orders
- Score folding: goals, own goals, penalties, shootouts
- Cards: second yellow produces a red; red-card count affects state
- Period handling: ET and penalty periods
- Every metric: PPDA, field tilt, progressive pass thresholds, possession chains
- Tie-breaks: every competition, including a **three-way tie** in La Liga
- Narrative selection: goals always included; near-duplicates suppressed;
  report length bounded
- Feature extraction matches a hand-computed vector for a known minute

### 20.2 Contract tests for feeds

One parametrised suite runs against **every** adapter using recorded fixtures:

```python
@pytest.mark.parametrize("adapter", [StatsBombAdapter(), FootballDataAdapter(), ApiFootballAdapter()])
async def test_adapter_conformance(adapter): ...
```

Asserts: normalised events validate against the canonical schema; declared
capabilities match what is actually produced; ids are stable across two fetches;
no invented fields.

### 20.3 Correction suite — the signature tests

```python
def test_disallowed_goal_removes_from_score_but_stays_in_timeline(): ...
def test_reinstated_goal_restores_score(): ...
def test_reassignment_changes_scorer_not_score(): ...
def test_correction_out_of_order_still_projects_correctly(): ...
def test_projection_is_identical_after_replaying_whole_log(): ...
def test_correction_regenerates_report_and_wp_series(): ...
def test_correction_changing_result_recomputes_league_table(): ...
def test_double_applied_correction_is_idempotent(): ...
```

**The property test that proves the model:**

```python
@given(events=event_log_strategy(), shuffle_seed=st.integers())
def test_projection_independent_of_arrival_order(events, shuffle_seed):
    """However events arrive, the projection is the same."""
    assert project(sorted_canonically(events)) == project(shuffled(events, shuffle_seed))
```

### 20.4 Integration

Redis, DynamoDB Local and MinIO as service containers. Covers: append→project→
publish round trip, consumer-group split, `XAUTOCLAIM` reclaim, WS cross-process
delivery, WS resume with `?since=`, Parquet archive → DuckDB query round trip.

### 20.5 Model gate

`tests/model/test_calibration.py` loads the held-out season, scores it, and fails
if the Brier score is worse than the committed threshold. Also asserts inference
under 5ms and full-match WP recompute under 200ms.

### 20.6 Page-weight test

Fetch `/m/{match_id}`, assert the response plus its critical CSS is under 100KB.

---

## 21. Benchmarks

`benchmarks/results/` holds committed JSON plus generated markdown.

### 21.1 Ingest throughput
```
Replaying World Cup 2022 (64 matches, ~205,000 events) at max speed, 4 workers

  events/sec sustained            X,XXX
  event -> state projected        p50 XXms   p95 XXms   p99 XXXms
  event -> pushed to browser      p50 XXms   p95 XXms   p99 XXXms
```

### 21.2 Correction propagation — the headline
```
  correction -> new projection written        XXms
  correction -> WP series recomputed          XXXms
  correction -> report regenerated            XXms
  correction -> table recomputed              XXms
  correction -> diff delivered to clients     p99 XXXms
```
Target: full propagation under 500ms at p99.

### 21.3 DuckDB vs DynamoDB
```
"All shots outside the box, La Liga, all seasons, grouped by player"
  DuckDB over Parquet on S3       XXXms
  equivalent DynamoDB scan        XX.Xs      (XXXx slower)
```

### 21.4 Model
```
  Brier (multiclass, held-out season)   0.XXX
  vs constant-prior baseline            0.XXX
  vs score-decides baseline             0.XXX
  log loss                              0.XXX
  inference                             X.Xms
```
Plus the reliability diagram image.

### 21.5 Page weight
```
  /m/{id} server-rendered       XX KB
  FotMob match page             X,XXX KB    (measured, cited, dated)
```

---

## 22. AWS and cost

| Stack | Contents |
|---|---|
| `NetworkStack` | VPC, 2 AZs, **public subnets only** (no NAT — saves ~$33/mo) |
| `DataStack` | DynamoDB on-demand, S3 archive bucket, ElastiCache `cache.t4g.micro` |
| `ComputeStack` | ECR, ECS cluster, ALB (idle timeout 300s), Fargate services `api` / `worker`, autoscaling on Redis stream backlog |

**Costs, and how to keep them near $35/month:** no NAT gateway; DynamoDB
on-demand; single-node `cache.t4g.micro`; Fargate Spot for workers; one shared
ALB; S3 Intelligent-Tiering on the archive.

- **Set a $20 billing alarm before the first `cdk deploy`.**
- Claim GitHub Student Pack / AWS Educate credits first.
- `cdk destroy` between demos; redeploy is ~12 minutes and it is all code.
- Local development never touches AWS.

Publish the cost table in the README. Cost-aware infrastructure decisions are
rare in student projects and land well.

---

## 23. Local development

`docker-compose.yml` runs: `redis`, `dynamodb-local`, `minio` (S3), `api`,
`worker` ×2, `frontend`. `docker compose up -d --build` must be the only command
needed to get a running system with a match replaying. Verify from a clean clone
before writing the README.

`Makefile`: `up`, `down`, `logs`, `seed`, `replay`, `train`, `test`, `lint`,
`types`, `bench`, `synth`, `check`.

---

## 24. CI

| Job | Contents |
|---|---|
| `quality` | ruff check, ruff format --check, mypy --strict |
| `unit` | pytest `tests/unit` + `tests/correction`, `--cov-fail-under=85` |
| `contract` | feed adapter conformance against recorded fixtures |
| `integration` | Redis + DynamoDB Local + MinIO services; API, WS, archive round trips |
| `model` | calibration gate — **fails if Brier regresses** |
| `docker` | build api/worker/frontend images |
| `cdk` | `cdk synth` only, never deploy |

Badge in the README on day one.

---

## 25. Six-week schedule

### Week 1 — domain and event model
1. Scaffold, pyproject, ruff/mypy, CI skeleton + badge, compose with Redis + DynamoDB Local + MinIO
2. `domain/events.py` — the full canonical taxonomy as Pydantic models
3. `domain/match_state.py` — the fold, with unit tests
4. `domain/corrections.py` — all four correction kinds + tests
5. StatsBomb download + parse into canonical events
6. `store/` — keys, event log append, projection read/write with versioning
7. Buffer

**Gate:** a real World Cup match parses into canonical events and projects to the
correct final score.

### Week 2 — corrections, replay, realtime spine
1. Correction propagation pipeline end to end
2. **The §20.3 correction suite, including the order-independence property test**
3. `replay/build_timeline.py` + `driver.py`
4. `replay/var_injector.py` with seeded determinism
5. Redis Streams ingest worker, consumer group, `XAUTOCLAIM` reclaimer
6. WS manager + pub/sub backplane; cross-process delivery test
7. Resumable `?since=` + `chanlog`

**Gate:** replay a match live, inject a VAR correction, watch the score correct
itself in a browser.

### Week 3 — archive, analytics, tables
1. Parquet writer, Hive partitioning, MinIO round trip
2. DuckDB session, analytical queries, `/api/analytics/*`
3. `domain/tables.py` + every tie-break strategy
4. Three-way-tie tests; table recomputation on correction
5. Derived metrics: PPDA, field tilt, progressive actions, possession chains
6. Pass-network computation
7. Buffer

**Gate:** DuckDB leaderboard across 10M archived events returns in under a second.

### Week 4 — model and narrative
1. `models/features.py` + the training-row builder over the archive
2. Elo computation from match history
3. Train logistic baseline, then LightGBM; season-based split
4. `evaluate_wp.py` — Brier, log loss, reliability diagram; CI gate
5. `predict.py` — <5ms, full-series recompute <200ms
6. `narrative/selector.py` — moment ranking and suppression
7. `narrative/templates.py` + `writer.py`; readable report on 20 real matches

**Gate:** calibration report committed; a World Cup final report reads well
enough to show someone.

### Week 5 — frontend
1. Vite + React + TS + Tailwind; typed client; `useLiveMatch`
2. `Pitch.tsx` with correct geometry; `ShotMap`; `FreezeFrame`
3. Match page: summary, timeline **with correction rendering**, stats
4. `WinProbabilityChart` with correction bands; `XgRace`; `PassNetwork`
5. Competition table with the tie-break explanation; team and player pages
6. Server-rendered `/m/{id}` low-bandwidth route + page-weight test
7. **Empty-state and copy pass across every screen**

**Gate:** clean clone → `docker compose up` → a match replaying in the browser
inside 60 seconds.

### Week 6 — AWS, benchmarks, README
1. CDK network + data stacks; billing alarm; deploy
2. CDK compute stack; ALB WebSockets verified
3. Autoscaling on stream backlog; verify scale-out
4. Run every benchmark in §21
5. Reliability diagram, screenshots, demo GIF of a correction landing live
6. README (§26); `ATTRIBUTION.md`
7. Buffer — something will have slipped

---

## 26. README structure

1. Title, CI badge, one-sentence description
2. **The problem** — an edited §2: what every soccer site gets wrong about
   corrections, and the gaps
3. **The GIF** — a goal going in, then being disallowed, the score correcting
   itself and the report regenerating live. *This is the single most important
   asset in the repo.*
4. Quick start
5. Screenshots — timeline with a correction, win-probability chart with the
   correction band, shot map with a freeze-frame open, generated match report
6. **How corrections work** — the §9 model; the order-independence property
7. **The win-probability model** — features, training, and the reliability diagram
8. **The match report** — moment selection, and why templates rather than an LLM
9. **Architecture** — why DynamoDB for live state and DuckDB over Parquet for
   analytics, with the §21.3 numbers
10. **Feed adapters** — the honest coverage statement from §4.2
11. Benchmarks — all of §21
12. Running costs
13. **Deliberately not built** — §6, one line each
14. **Known limitations** — synthesised VAR corrections in the demo; no global
    live coverage without a paid feed; entity resolution is imperfect and the
    unresolved count is published
15. Attribution — StatsBomb, per licence
16. Project structure

---

## 27. Resume entry

> **Onside — Live Soccer Match Intelligence Platform** *(Python, FastAPI, DynamoDB, Redis, DuckDB, React, AWS, LightGBM)*
> Event-sourced soccer platform that stays correct when VAR overturns a goal, and auto-generates a match report from win-probability swings
> - Designed an append-only event store with first-class corrections over **10M+** match events; retroactive VAR overturns rebuild match state, win probability, the league table and the generated report in **under XXXms** end-to-end, verified by a property test asserting projection is independent of event arrival order
> - Trained a calibrated live win-probability model (LightGBM, **320K** match-state rows, season-based split) reaching a **0.XXX** multiclass Brier score, served at **<5ms**, with CI blocking merges on calibration regression
> - Split storage by workload — DynamoDB for live state, Parquet on S3 queried by DuckDB for analytics — making cross-season aggregates over 10M events **XXXx** faster than an equivalent scan
> - Built a feed-agnostic adapter layer with contract tests across three providers, including cross-feed entity resolution with a published unresolved-entity count

---

## 28. Interview preparation

| Question | Where the answer lives |
|---|---|
| "Why event sourcing?" | §9: soccer data changes retroactively; a mutable row cannot answer "was it ever 2-1?" |
| "How do you know the projection is right?" | §20.3: the order-independence property test |
| "What happens when a correction arrives late?" | §9.3: rebuild, diff, publish the diff not a snapshot |
| "How do you know the model is any good?" | §13.3: Brier vs two baselines, reliability diagram, CI gate |
| "Why not an LLM for the report?" | §14.3: explainable, free, cannot hallucinate, regenerates on correction |
| "Why two databases?" | §11: key-lookup live state vs. analytical scans; with the measured gap |
| "Why DuckDB and not Spark or Athena?" | 10M rows is far below where DuckDB struggles; no cluster, no cost |
| "How do you handle feeds disagreeing?" | §12.4: documented precedence, conflicts counted and surfaced |
| "You don't have global coverage." | §4.2: feed-agnostic by design; adapter written and contract-tested; it's a subscription, not a rewrite |
| "What would you do next?" | Real VAR feed; xT model trained on the archive; per-referee correction analytics |

---

## 29. Definition of done

- [ ] `docker compose up -d --build` → a match replaying within 60s
- [ ] All seven CI jobs green; badge in the README
- [ ] `mypy --strict` clean; coverage ≥85%
- [ ] Order-independence property test green over 1,000 generated cases
- [ ] Full correction propagation measured under 500ms p99
- [ ] Model calibration report committed; reliability diagram in the README
- [ ] DuckDB vs DynamoDB comparison measured
- [ ] `/m/{id}` under 100KB, asserted in a test
- [ ] Deployed to AWS; benchmarks run; `cdk destroy` verified; billing alarm live
- [ ] **The correction GIF** recorded and in the README
- [ ] Every empty state has written copy
- [ ] `ATTRIBUTION.md` credits StatsBomb per licence, and the app footer does too
- [ ] Synthesised VAR corrections labelled as synthesised everywhere they appear
- [ ] Resume bullets updated with real measured numbers

---

## 30. Advice to the building session

1. **Corrections are the project.** If the schedule slips, cut the pass network,
   cut the player pages, cut the low-bandwidth route. Do not cut §9, §20.3, or
   the GIF that shows a score correcting itself. Without those this is another
   scores site.
2. **Build the replay engine in week 2.** Everything downstream — the demo,
   benchmarks, manual testing — depends on generating realistic live events on
   demand.
3. **Keep `domain/` free of I/O.** The fold, the tie-breaks and the narrative
   selector are pure functions and should be trivially testable.
4. **Never invent data.** If a feed lacks xG, the field is absent and the UI says
   so. Fabricated completeness is the fastest way to lose credibility.
5. **Label the synthesised VAR corrections everywhere.** Honesty here is part of
   what the project is arguing for.
6. **Write the model evaluation before tuning the model.** Otherwise you will
   tune against a number you have not defined.
7. **Set the AWS billing alarm before the first deploy.** Not after.
8. **Record numbers as you go.** Every improvement, before and after. They become
   README lines and interview answers, and you will not remember them later.
9. **Keep the out-of-scope list closed.** Accounts, notifications and transfer
   news are each a week that would otherwise go into corrections, calibration and
   the README — the three things that make this land.
