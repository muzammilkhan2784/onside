# Onside

**Correction-aware soccer match intelligence. This week's real fixtures, tables and scorers; what fans are posting about them; and every match in the StatsBomb open-data archive with a calibrated win-probability model and a report that rewrites itself when VAR takes a goal away.**

[![CI](https://github.com/muzammilkhan2784/onside/actions/workflows/ci.yml/badge.svg)](https://github.com/muzammilkhan2784/onside/actions/workflows/ci.yml)

> *Onside*: level with the last defender — and the call that still stands after the review.

```bash
docker compose up -d --build     # web on :5173, API docs on :8080/docs
```

One command brings up the API, two ingest workers, the reclaimer, the replay
service, the fixtures and social workers and the web app, and builds an archive
if there isn't one. Put your keys in `.env` first (see [.env.example](.env.example))
to switch on current fixtures and the social feed. Every archived match reads as what it is - finished, with its date
and full-time result. Nothing replays until someone asks: open any match and
press **Watch the replay** (or use the Replays page), and it re-runs minute by
minute through the live pipeline, marked as a replay in violet, with a
synthesised VAR check that corrects the score in front of you.

---

## The problem

Seven sites already show you the score. None of them handle the thing that
makes soccer data genuinely hard: **it changes retroactively.**

A goal goes in at 35'. At 37' VAR rules it out. On every major scores site the
number silently changes and the goal is simply *gone* — no record that it was
ever given, no reason, no timestamp, and no way to ask what the score was at
36'. The same happens when a scorer is reassigned or an xG value is revised.

| Site | Best at | Doesn't do |
|---|---|---|
| FlashScore | Fastest updates, widest coverage | Almost no depth; corrections happen silently |
| Sofascore | Deepest live stats, heat maps | No calibrated win probability; no correction history |
| FotMob | Best live UI, xG, ratings | No audit trail; no synthesised explanation |
| FBref / StatsBomb | Deepest historical analytics | Not live; no narrative |
| Understat | Good public xG | Few leagues; not live |

Five gaps none of them fill:

1. **Corrections are invisible.** Nobody shows *what* changed, *when*, or *why*.
2. **"I missed the game" is unsolved.** Highlights are rights-locked; text recaps are wire copy or a stat dump. Nobody ranks the moments that actually decided it.
3. **Calibrated live win probability is rare in soccer.** Standard in the NFL and NBA. Nobody publishes a Brier score or a reliability diagram.
4. **No data provenance.** Two sites report different xG for the same shot and neither says which model.
5. **No developer-grade free API over deep event data.** The good feeds are €99–249/month.

---

## What's in it

**13,911,986 events across 3,961 matches, 24 competitions and 80 seasons, from 1958 to 2025** — every pass, carry, duel and shot with pitch coordinates, expected goals and 360° freeze-frames. Every match has its own page, its own generated story, and a row in a public API.

| | |
|---|---|
| **The hub** | Front page, news feed of generated stories, competitions, seasons, fixtures, tables, teams, players, search |
| **The match page** | Broadcast scoreboard, win-probability river, timeline with corrections inline, stats with plain-English glosses, shot map with freeze-frames, pass networks, formation line-ups on the pitch, generated report |
| **Replays** | Re-run any archived match through the real pipeline, clearly labelled as a replay with the real result alongside; pause, resume, change speed, inject a VAR check |
| **Matches** | This week's real fixtures and results, current tables and top scorers for 12 competitions via football-data.org, with a green LIVE badge only a real match in play can carry (free API key) |
| **Buzz** | A social dashboard: public Bluesky and Mastodon posts about the matches being played, matched to fixtures, de-duplicated, with trends, hourly volume and per-source status. Reddit and X adapters are built and switch on with keys |
| **The API** | 47 documented endpoints plus WebSockets, at `/docs` |
| **Low bandwidth** | Every match at `/m/<id>`: server-rendered, no JavaScript, **2.6 KB** |

---

## The three things that make it not a CRUD app

### 1. The event log is append-only. Nothing is ever updated or deleted.

Match state is a pure fold over the log:

```python
def project(log: Sequence[LogRecord]) -> MatchState:
    """Deterministic. Same records in, same state out — however they arrived."""
```

A VAR overturn is not an edit. It is a new record that *supersedes* an earlier one:

```python
Correction(supersedes="a1b2c3…", kind="disallow", reason="Handball in the build-up",
           authority="VAR", decided_at_minute=37)
```

| kind | effect on the projection |
|---|---|
| `disallow` | Stops counting. **Stays visible in the timeline, struck through, with the reason.** |
| `reassign` | Attribution changes; the score does not. |
| `amend` | One field changes (xG revised, minute corrected). |
| `reinstate` | A previous `disallow` is itself reversed. |

Because nothing is destroyed, the match page has a scrubber that answers a
question no mutable-row site can answer at all:

```
GET /api/matches/live-3869685/score-at?period=1&minute=36   ->  2-0
GET /api/matches/live-3869685/score-at?period=1&minute=40   ->  1-0
```

A correction moves **every** number, not only the score: the win-probability
series, both sides' metrics, the shot map and the report are all rebuilt from
the corrected log.

### 2. A calibrated win-probability model

LightGBM over **360,451 per-minute match states**. Ten features, all things a
person watching could tell you. Trained on 288,288 rows from 3,168 matches
before 2023-10-07, tested on 72,163 rows from the 793 matches after.

| Multiclass Brier (lower is better) | |
|---|---|
| **LightGBM** | **0.4042** |
| Multinomial logistic regression | 0.4114 |
| Baseline: "whoever is ahead wins" | 0.4694 |
| Baseline: constant class prior | 0.6486 |

Log loss 0.697 against 0.813 for the score-decides baseline. Inference 0.10 ms.

**The reliability diagram is diagonal**, which is the claim that matters for a
probability — not accuracy:

| Predicted | 0.036 | 0.145 | 0.250 | 0.345 | 0.448 | 0.546 | 0.652 | 0.750 | 0.848 | 0.966 |
|---|---|---|---|---|---|---|---|---|---|---|
| **Observed** | 0.039 | 0.147 | 0.238 | 0.339 | 0.442 | 0.555 | 0.707 | 0.780 | 0.808 | 0.969 |

Calibration is also published **by minute bucket**, because a live model is
sharp late and vague early and hiding that behind one number would be dishonest:

| Minute | 0–15 | 15–30 | 30–45 | 45–60 | 60–75 | 75–90 |
|---|---|---|---|---|---|---|
| Brier | 0.532 | 0.493 | 0.448 | 0.400 | 0.330 | **0.241** |

**CI fails the build if any of this regresses.** The thresholds are committed in `backend/tests/model/`.

### 3. Reports written by rules, not a language model

Every moment is ranked by how far it moved the win probability; the top ones
are templated into prose. Real output, mid-replay, after the VAR check:

```
Argentina 1-0 France — FIFA World Cup, 18 December 2022

 22' — Lionel Messi converted the penalty to make it 1-0.
       That moved Argentina from 50% to 75% to win.
 35' — Ángel Di María put the ball in the net for Argentina, but it was
       ruled out at 39': handball in the build-up. The score stayed 1-0.
```

No LLM: every sentence comes from a rule, so it is explainable, reproducible,
free, cannot hallucinate a goal — and regenerates the instant a correction
lands. An LLM layer could sit on top; the system does not need one.

---

## Architecture

```
 StatsBomb / football-data / API-Football
                │  adapters normalise into one canonical event model
                ▼
        Redis Streams (sharded by match, one owner per shard)
                │
        ingest workers ──▶ append-only log (DynamoDB)
                │                    │
                │            project(log)  ← pure fold, no I/O
                ▼                    │
        Redis pub/sub ◀── diff ──────┤
                │                    ├──▶ match state, win probability,
        WebSocket gateways           │    report, shot map, pass networks
                │                    ▼
            browsers          Parquet on S3 ──▶ DuckDB (analytics)
```

**Why two stores.** DynamoDB answers "this match, right now" in single-digit
milliseconds. It is the wrong tool for "every shot from outside the box in La
Liga, by player" — that is an analytical scan, and it belongs in columnar
Parquet read by DuckDB in-process. No cluster, no cost, and 14 million rows is
far below where DuckDB struggles.

**Why the ingest log is sharded.** Each match's events go to one of eight
streams; a worker holds a Redis *lease* on a shard, so every match has exactly
one writer and that writer keeps the match's log in memory. It only reads the
log back from DynamoDB on a cold start, a lease handover, or a replay restart.
Writes are still conditional on a version, so a lease that expires mid-batch
can't corrupt anything — the loser re-reads and retries.

```
backend/onside/
├── domain/        pure logic, zero I/O: events, the fold, corrections,
│                  tie-break rules, metrics, the narrative engine
├── feeds/         adapter protocol + StatsBomb, football-data, API-Football
├── store/         single-table DynamoDB: keys, codec, repositories
├── archive/       Parquet writer, DuckDB session, analytical SQL
├── streams/       Redis Streams and pub/sub
├── social/        Bluesky, Mastodon, Reddit and X sources, topic matching, store
├── workers/       ingest worker, projector, reclaimer, fixtures and social pollers
├── models/        features, dataset builder, training, inference
├── ingest/        match document builder, archive build, seed, catalog
├── replay/        open-data fetch, wall-clock schedule, VAR injector, driver
└── api/           FastAPI: routes, schemas, errors, WebSockets, lite pages
frontend/src/      React 18 + TypeScript + Vite + Tailwind + TanStack Query
infra/             AWS CDK: the free tier (one stack, the default) and the
                   full deployment; onside_secrets.py, free_check.py
```

---

## Measured

On a laptop (32 cores) with the data services in Docker. Reproduce with `make bench`.

**Building the archive.** 3,961 matches downloaded, normalised, projected,
modelled, reported and written to Parquet in **5.4 minutes**, 16 workers, zero
failures — 13.9M events.

**What a correction costs.** Rebuilt from the log, not patched:

| Step | p50 | p95 |
|---|---|---|
| Rebuild match state (4,407 events) | 8.9 ms | 26.6 ms |
| Recompute the 90-minute win-probability series | 6.8 ms | 12.8 ms |
| Regenerate the report | 34.7 ms | 62.1 ms |
| **Rebuild the whole document** | **80.5 ms** | **95.0 ms** |

**Ingest.** One worker, one match, against DynamoDB Local in Docker:

| | |
|---|---|
| Projection throughput | **463 events/second** |
| End to end | 51 events/second |
| Where the time goes | **81% DynamoDB Local**, 12% projection, 7% stream I/O |

The honest read: the emulator is the bottleneck, not the pipeline. Managed
DynamoDB writes roughly an order of magnitude faster, and the projection number
does not depend on the store at all.

**Why storage is split by workload.** "Every shot from outside the box in La
Liga, grouped by player" — 867 matches, 3,132,716 events:

| | |
|---|---|
| DuckDB over Parquet | **783 ms** |
| Reading the same events from DynamoDB | ~23 minutes (projected from a measured 10-match sample) |
| | **~1,800×** |

The DynamoDB figure is a projection on purpose: keeping 3.1M event items in
DynamoDB to answer one analytical question is exactly what the split exists to
avoid. A full count over all 13.9M archived events takes DuckDB **108 ms**.

**Page weight.** `/m/<id>` is **2.6 KB**, no JavaScript, screen-reader friendly.

---

## Honest about the data

- **This is not every game in the world.** It is every match StatsBomb publishes free: 3,961 of them. Global live coverage needs a paid feed. The adapter layer is built for one — `ApiFootballAdapter` is implemented and contract-tested, and enabling it is a config change and a subscription, not a rewrite.
- **The VAR corrections in replays are synthesised.** StatsBomb's open data records no VAR decisions, so `replay/var_injector.py` generates realistic ones deterministically from the real event stream. Every one carries `synthesised=True` through the whole system and is labelled wherever it appears. The API-Football adapter maps that feed's real `Var` → "Goal cancelled" events into genuine corrections; that path is contract-tested.
- **No table is shown where coverage is partial.** Most La Liga seasons in the archive are one club's matches. A table built from them would be wrong, so the season says how many matches it holds and why there is no table.
- **Group letters are inferred.** StatsBomb doesn't record them; groups are recovered from who played whom and numbered by kick-off, and the page says so.
- **Win probability covers regulation.** The target is the result at 90 minutes, where "draw" still means something. Extra time and penalties are outside the model's range and no figure is quoted for them.
- **Elo is weak for international sides**, which play rarely. It is computed causally — a rating never contains information from the match it is used to predict.

---

## Three bugs worth writing down

**Splitting train/test by competition.** The first model trained on World Cup
2022 and tested on Euro 2024. Elo was rebuilt per competition, so every test
team sat on the default 1500 rating — a different distribution from training.
It scored *worse than "whoever is ahead wins"* (0.6265 vs 0.4694). The fix was
the date-based split the spec had asked for.

**Train/serve skew in the browser.** Training rows describe the state at the
*start* of a minute; the demo exporter was including that minute's events. Then
a subtler version of the same bug: first-half stoppage time makes minutes
non-monotonic at the period boundary (a period-1 event at 47' sorts before a
period-2 event at 45'), which stalled a cursor-based accumulator. Training and
serving now call **one shared accumulator**, and a test fails if they disagree
by a single minute.

**Rounding the model into the wrong answer.** LightGBM encodes a "zero versus
positive" split with a threshold of about `1e-35`. The browser export rounded
thresholds to six decimal places, collapsing that to `±0.0` and flipping the
routing for any feature that is exactly zero — which is every feature at
kick-off. Random test inputs agreed to seven decimals; the page still showed
nonsense at minute 0. Browser and booster now agree to 1e-9, and a test checks
a zero-heavy grid specifically, because random sampling will never find it.

---

## Tests

```bash
make test        # 239 backend tests (plus 38 in the web app: npm test)
make check       # ruff, mypy --strict on the domain, tests, web typecheck
```

- **The property test that proves the model** — `project()` is order-independent and duplicate-insensitive over generated logs, because feeds deliver out of order and redeliver on reconnect.
- **The correction suite** — disallow, reinstate, reassign, amend, out-of-order arrival, double application, and "was it ever 2-0?".
- **Contract tests across all three adapters** — capabilities match what is produced, ids are stable, provenance survives, and nothing is invented where a feed is shallow.
- **Live pipeline integration** — a replay through streams, workers, log, projection and published diffs, with redelivery and dead-worker recovery, on in-process DynamoDB (moto) and Redis (fakeredis). No Docker needed in CI.
- **Tie-breaks** — including a three-way tie, and the same results producing a different table in La Liga and the Premier League.
- **The model gate** — Brier, log loss, calibration by minute, and the browser export matching the booster.

---

## Running it

```bash
make up          # everything in Docker
make data        # build the full archive (3,961 matches; ~12 GB downloaded)
make train       # rebuild the training set and the model
make bench       # measure everything above
make down
```

Without Docker: `pip install -e "backend[dev]"`, run Redis and DynamoDB Local,
then `uvicorn onside.api.main:app` and `npm --prefix frontend run dev`.

### Keys for the outside feeds

Copy the keys you have into a file called `.env` next to `docker-compose.yml`
(it is git-ignored *and* Docker-ignored, so it is never committed and never
baked into an image). Each worker receives only its own keys.

| Feed | Key | What it switches on | Cost |
|---|---|---|---|
| football-data.org | `FOOTBALL_DATA_API_KEY` | Matches page, home hero, tables, scorers | Free ([register](https://www.football-data.org/client/register)) |
| Bluesky | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | Bluesky in the Buzz feed | Free (Settings → App passwords) |
| Mastodon | none | Mastodon in the Buzz feed | Free |
| Reddit | none (the public r/soccer feed); `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` for the API | r/soccer in the Buzz feed | Free (Reddit approves API apps by hand; the feed needs nothing) |
| X | `X_BEARER_TOKEN`, `X_MAX_READS_PER_DAY` | X in the Buzz feed, with a hard daily cap | Pay-per-use, about $0.005 a post read |

The fixtures worker spends at most four requests a minute against the free
tier's ten. The social worker runs every two minutes (five on the free-tier
deployment), drops repeats, caps any
single account at eight posts in six hours, skips sensitive posts and replies,
and respects authors' opt-outs (Bluesky's `!no-unauthenticated`, Mastodon's
`noindex`). Without a key, every page says what is off and why instead of
showing an empty list. `ApiFootballAdapter` (global coverage, native VAR
events) is implemented and contract-tested but not wired to a service.

To change a key - after rotating it at the provider - use
`python infra/onside_secrets.py --set BLUESKY_APP_PASSWORD` (any key name works).
It asks for the value with typing hidden, so the key never lands in shell
history, and updates both `.env` and the AWS deployment's copy.

### On AWS, free

```bash
cd infra && pip install -r requirements.txt
python onside_secrets.py                    # the keys in ../.env -> SSM Parameter Store
npm --prefix ../frontend run build
npx aws-cdk deploy OnsideFree
cd ../backend && ONSIDE_ENV=aws ONSIDE_TABLE=onside-free python -m onside.ingest.seed
```

`OnsideFree` is the only stack the app defines by default, so `cdk deploy
--all` cannot start an ElastiCache node, a NAT gateway or a load balancer by
accident; the paid deployment needs `-c profile=full` and its own name.

One stack on services that stay inside AWS's always-free allowances:
CloudFront in front of an S3 bucket holding the web app, a Lambda running the
unchanged FastAPI app behind the [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter),
a second Lambda for the fixtures and social jobs on EventBridge schedules, and
DynamoDB. Nothing in it is billed by the hour.

The one thing with no free tier is Redis (ElastiCache), so this deployment has
none. What Redis holds for the fixtures and social workers - strings, hashes,
sorted sets - lives in a second DynamoDB table instead, behind
[`DynamoKV`](backend/onside/store/kv.py): the same commands with the same
answers as redis-py, checked by running the same tests against both. It is
provisioned at 20 read and 20 write units, inside the always-free 25. The
Parquet archive ships inside the Lambda image, compacted at build time into
one file sorted by player ([`compact.py`](backend/onside/archive/compact.py)).
On Lambda's single vCPU, opening a file per match cost 2.8 seconds for one
player's career even when warm; the compacted file answers the same query,
with identical results (a test checks), in about 100 ms warm - 1.4 s on
the first query after a cold start. Replays and WebSockets need Redis
Streams and always-on workers, so here they are off: the web app asks
`/api/features` and says so instead of offering buttons that fail. Everything
else is the same code.

Secrets are SecureString parameters, read by the worker at start-up and every
fifteen minutes after, so a rotated key takes effect without a redeploy.
They never pass through CloudFormation or the image.

**What it costs.** Nothing in it is billed by the hour, and the allowances it
lives inside do not expire: CloudFront's first terabyte and ten million
requests a month, Lambda's million requests and 400,000 GB-seconds, DynamoDB's
25 GB and 25 provisioned units (the key-value table takes 20 of them), 3 days
of logs, and standard Parameter Store. Three things still add up slowly:
stored container images (about $0.10 a GB a month), requests against the
on-demand table (12.5 cents a million reads), and the S3 the site is served
from - cents a month between them.

```bash
python infra/free_check.py          # what, if anything, is billed by the hour
python infra/free_check.py --fix    # keep 2 images, bound Onside's log retention
```

It is read-only without `--fix`, exits non-zero if it finds an instance, a
load balancer, a NAT gateway, a database, a Redis node or an unattached disk
anywhere in the region, and prints how much of each free allowance this month
has used.

### On AWS, the full deployment

```bash
cd infra && pip install -r requirements.txt
npx aws-cdk deploy OnsideBilling -c profile=full --context alarmEmail=you@example.com
npx aws-cdk deploy OnsideNetwork OnsideData OnsideCompute -c profile=full
```

Four stacks, 76 resources (83 with today's fixtures: store the key in Secrets
Manager and add `--context footballDataSecret=<secret name>`): a $20 billing alarm (deployed first, and everything
else depends on it), a VPC with **no NAT gateway**, DynamoDB on-demand, an S3
archive with Intelligent-Tiering, one `cache.t4g.micro` Redis, and ECS Fargate
behind one ALB. Workers, reclaimer and replay run on **Fargate Spot** — safe
precisely because of the design: a reclaimed task's messages stay pending, its
leases expire, and the reclaimer hands the work to someone else.

Target cost is about **$35/month** while running; `npx aws-cdk destroy` of
those stacks between demos takes it to zero. CI only ever runs `synth`.

---

## Attribution

Event data from [StatsBomb Open Data](https://github.com/statsbomb/open-data),
free for research and education. Full credit and licence terms in
[ATTRIBUTION.md](ATTRIBUTION.md). Onside is an independent portfolio project
and is not affiliated with StatsBomb.

> Data provided by StatsBomb.
