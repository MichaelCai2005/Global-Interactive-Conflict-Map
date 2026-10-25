<img src="frontend/public/favicon.svg" alt="" width="64" align="left" />

# Conflict Atlas

<br clear="left" />

A system for studying how conflicts emerge: it pulls together records of past violence and
the news signals that came before it (protests, threats, troop movements), cleans and links
them, and serves them through an API that a map dashboard and, later, an AI analyst can use.

## Roadmap

1. **Data pipeline and API** (this stage): load three differently formatted sources, clean,
   validate and dedupe them, store them in Postgres with PostGIS, and serve them with FastAPI.
2. **Map dashboard**: a React and TypeScript map with filters, a watchlist and analyst tasks.
3. **Risk signals and AI**: explainable per-region trend scores that show which signals
   came before past violence, question-answering over reports with citations, and drafted
   actions that wait for human approval.
4. **Hardening**: authentication, logging, retries, and an evaluation set measuring
   accuracy, latency and cost.

## Data sources

| Source | What it is | Format | Role here |
| --- | --- | --- | --- |
| [UCDP GED](https://ucdp.uu.se/downloads/) | Hand-coded events of organized violence with at least one death, 1989 onward | CSV with header | What actually happened |
| [ACLED](https://acleddata.com/) | Hand-coded political violence, protests, riots and strategic developments, 1997 onward (varies by region) | JSON API, saved as CSV | Violence plus the non-lethal events around it |
| [GDELT 1.0 / 2.0 events](https://www.gdeltproject.org/data.html) | Machine-coded news events (CAMEO), 1979 onward | Tab-separated, no header, 57/58/61 columns | Signals before and around violence |

ACLED needs an account. Free research accounts only see events more than 12 months old,
which suits studying how past conflicts developed. ACLED's terms limit redistributing its
raw data, so check them before serving ACLED records from a public site or API.

Country-year structural indicators, for the slow-moving drivers that explain where conflict
is likely:

| Source | What it adds | Format | Access |
| --- | --- | --- | --- |
| [World Bank WDI](https://data.worldbank.org/) | GDP per capita and growth, inflation, unemployment, infant mortality, population, urbanisation, resource rents, military spending | JSON API, saved as CSV | Open, downloaded by the CLI |
| [V-Dem](https://v-dem.net/data/the-v-dem-dataset/) | Electoral and liberal democracy, regime type, civil liberties, political violence, corruption, rule of law | CSV, one row per country-year | Free, but behind a registration form: download "Country-Year: V-Dem Core" yourself |
| [EPR Core](https://icr.ethz.ch/data/epr/core/) | Population share of ethnic groups excluded from or discriminated against by the state, groups in power | CSV of group periods, turned into country-year totals | Open, downloaded by the CLI |

Every source codes countries its own way (Gleditsch-Ward numbers in UCDP and EPR, ISO
numeric in ACLED, FIPS in GDELT, V-Dem ids), so `backend/app/data/countries.csv` maps them
all to ISO3. Events carry the result in `country_iso3`.

Planned next: triggers (coups, elections, food prices, drought) and VIEWS forecasts as a
benchmark, then social media. X's API charges for read access, so Telegram channels or
Bluesky are likely better first social sources.

## How the pipeline handles messy data

Every row ends up in exactly one bucket, and each ingest run records the counts:

- **Filtered out**: valid but out of scope. GDELT cooperation events (CAMEO roots 01-12)
  are dropped; only conflictual roots 13-20 are kept. Every ACLED event type is kept:
  battles, explosions and violence against civilians count as violence, while protests,
  riots and strategic developments are signals.
- **Rejected**: stored in `rejected_records` with the raw row and every reason it failed:
  missing or unparseable fields, coordinates out of range or at 0,0, dates in the future or
  before 1946, end date before start date, fatalities not ordered low <= best <= high, no
  usable location, unknown ACLED event type or precision code.
- **Merged in file**: duplicates within a file. UCDP and ACLED rows share an event id; GDELT rows
  share a fingerprint (date, CAMEO code, both actors, location rounded to ~100 m), because
  GDELT writes one row per article about the same incident.
- **Inserted / updated**: upserted on `(source, dedupe_key)`, so reloading a file is
  safe. A newer UCDP release or ACLED download overwrites revised events; a GDELT incident seen again keeps
  its highest mention count.
- **Cross-source duplicates**: a violent event from a lower-priority source within 25 km
  and 1 day of one from a higher-priority source is linked to it in `event_links` and marked
  `duplicate_of_id`. Country-level locations are never linked, since a country centroid says
  nothing about where something happened. Priority is UCDP, then ACLED, then GDELT.

All events share one schema: date range, `event_type`, `is_violent` (violence vs signal),
location with precision (`exact`, `admin`, `country`), actors, fatalities, report count,
tone, and source-specific extras in `attributes`.

Indicator rows follow the same buckets. Regional aggregates (World, Sub-Saharan Africa),
historical states with no present-day successor (East Germany, South Vietnam) and years
before 1946 are filtered out. Values upsert on `(source, indicator, iso3, year)`, so a new
release overwrites revised values.

## Features for forecasting

Forecasting models need one row per place and month. `build-features` writes
`cell_month_features`, keyed by [PRIO-GRID](https://grid.prio.org/) 0.5 degree cell and
month. Each event's cell is derived from its coordinates, and matches the `priogrid_gid` UCDP
publishes. Country-level locations get no cell. Each row holds:

- **This month**: UCDP events and deaths, violent incidents from any source (counted once),
  ACLED events, deaths, protests and riots, GDELT threats, protests, force posture,
  coercion and violence, GDELT mentions and mention-weighted tone.
- **History**, from earlier months only, so it can predict this one: UCDP deaths in the
  last 1, 3, 12 and 36 months, months since the last violent event (empty if none in 36),
  deaths in the eight neighbouring cells last month and over the last year, and GDELT
  protests and threats over the last 3 months.

`GET /features/cells` adds each cell's country indicators from the latest year *before* the
month's year, so a backtest never uses a value that wasn't published yet. Cells with no
events in a range or the 36 months before it have no rows: treat them as zeros. Rebuild a
range after loading new events.

## Weekly risk scores

`python -m app.risk build` scores every country every week (weeks start on Monday) from the
events table, following the "Scoring Conflict Risk Over Time" design. A score is 0-100 and
is the sum of four parts, so the map can always say why a country is red:

| Part | Question | How | Max points |
| --- | --- | --- | --- |
| History | How violent lately? | UCDP and ACLED deaths, fading with a 26-week half-life; log scale, 10,000 decayed deaths is full | 54 |
| Surge | Is this week abnormal here? | z-score of log(1 + violent events) against weeks t-56 to t-5, accumulated by a CUSUM (alarm at 4, capped at 8) | 15 |
| Spread | Are neighbours heating up? | Mean History of countries with events within about 165 km | 11 |
| Signal | Is the news turning? | GDELT share of world conflict news, Goldstein score and tone, each against the country's own baseline | 20 |

A part no country has data for that week is left out and the rest scale up to 100. Each
source's surge is measured only against weeks that source covers, so loading ACLED for one
year doesn't read as a war starting. Weeks UCDP and ACLED don't wholly cover yet are marked
provisional. Each week also gets a 12-week trend tag (new, intensifying, diminishing,
persistent; Mann-Kendall test plus a 10-point minimum change). Changes and trends compare
like with like: an earlier week scored from other parts is scored again from this week's,
so the scale-up when Surge drops out doesn't read as every country rising at once. Rising
and Falling use the newest week UCDP and ACLED wholly cover.

The dashboard's Risk tab follows the timeline: as the window moves, it ranks countries for
that week, and for a country shows the score by part over time, a sentence on what moved
it, and the week's deadliest events. Rebuild after loading new events; on all of UCDP it
takes about 15 seconds.

### Fitted weights and backtest

The weights are fitted, not set by hand. `python -m app.risk_model fit` (needs numpy:
`pip install -e ".[model]"`) fits the design doc's
negative binomial model of the next four weeks' deaths on History, Surge and Spread, and
writes the weights to `backend/app/data/risk_weights.json`, which `app.risk build` reads.
Because the model uses a log link, the weights are the model's coefficients scaled to the
points they share, so the score is still a sum of parts. Signal can't be fitted: GDELT is
loaded for only about 19 weeks. It keeps its hand-set 20 points until more is loaded.

`python -m app.risk_model backtest` grades the weights with rolling-origin tests. Each year
from 2000 to 2025 is scored with weights fitted only on earlier years. Results on UCDP
1989-2025 (170,352 country-weeks):

| Weights | Any 25+ deaths next 4 weeks (AUC / AP) | Flare-up in a quiet country (AUC / AP) | Top 10 precision |
| --- | --- | --- | --- |
| Fitted | 0.968 / 0.822 | 0.829 / 0.032 | 0.862 |
| Hand-set 40/20/20 | 0.960 / 0.787 | 0.818 / 0.032 | 0.836 |
| History alone | 0.972 / 0.849 | 0.814 / 0.027 | 0.884 |

AUC is the chance a violent week outranked a calm one. AP (average precision) rewards
putting violent weeks at the very top. A quiet country is one with fewer than 25 deaths in
the past 26 weeks.

What this shows:

- Fitted beats hand-set on every measure.
- The fitted weights barely move from one test year to the next: History rises from 41 to
  54 points, Surge stays at 15-20, Spread drops from 22 to 11.
- History alone ranks ongoing wars best. Surge and Spread pay off on flare-ups in quiet
  countries, the case an analyst most needs to see. Even there, only about 3% of the
  highest-ranked quiet weeks turn violent, against a base rate of 0.6%.
- Out of sample, 30% of weeks scoring 40-50 saw 25+ deaths in the next four weeks; at
  60-70 it was 89%.
- A half-life of 26 weeks for History beat 4, 8, 13 and 52 weeks on the model's fit
  (`--half-life` reruns it).

[docs/risk-backtest.md](docs/risk-backtest.md) has the full report, with calibration by
score band and the known weeks. Refit and rebuild after loading a new UCDP release.

## Running it

With Docker:

```bash
docker compose up --build          # API on http://localhost:8000, docs at /docs
docker compose exec api python -m app.ingest download gdelt --start 2022-02-01 --end 2022-02-28
docker compose exec api python -m app.ingest download ucdp --version 26.1
docker compose exec api python -m app.ingest download acled --start-year 2022 --country Ukraine
docker compose exec api python -m app.ingest load gdelt data/gdelt/*.zip
docker compose exec api python -m app.ingest load ucdp data/ucdp/ged261-csv.zip
docker compose exec api python -m app.ingest load acled data/acled/*.csv
docker compose exec api python -m app.ingest download wdi --start-year 1989 --end-year 2025
docker compose exec api python -m app.ingest download epr
docker compose exec api python -m app.ingest load wdi data/wdi/wdi-1989-2025.csv
docker compose exec api python -m app.ingest load epr data/epr/EPR-2021.csv
docker compose exec api python -m app.ingest load vdem data/V-Dem-CY-Core-v16_csv.zip
docker compose exec api python -m app.ingest build-features --start 1990-01 --end 2025-12
docker compose exec api python -m app.risk build
```

ACLED downloads read `ACLED_EMAIL` and `ACLED_PASSWORD` from `backend/.env` (git ignores
it). `--country` repeats; leave it out for every country. Each country and year becomes one
CSV. Files for older years are kept, and the last two years are downloaded again because
ACLED keeps revising them. Files from ACLED's export tool load the same way.

Load sources in any order; linking runs after every load. Check the current
UCDP release number on its downloads page. Events loaded before country codes existed
(migration 0004) have an empty `country_iso3` until their files are loaded again.

Without Docker, with a local Postgres that has PostGIS:

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env               # point DATABASE_URL at your database
alembic upgrade head
uvicorn app.main:app --reload
```

Tests need a PostGIS database at `TEST_DATABASE_URL`
(default `postgresql+psycopg://conflict:conflict@localhost:5432/conflict_test`):

```bash
ruff format --check . && ruff check . && pytest
```

To put the map online (hosted database, API and frontend, kept current nightly, with
ACLED left out as its license requires), see [docs/hosting.md](docs/hosting.md). The root
`Dockerfile` and `render.yaml` deploy the whole site as one service.

Visitors can browse without an account. Signing up (email and password) lets each person
keep their own watchlist, tasks, boards and saved searches: map views to reopen, and the
topics they've searched (the **Saved** tab). On a local install with no `ADMIN_TOKEN`,
everything works without signing in, in one shared workspace.

## Map dashboard

`frontend/` is a React and TypeScript app (Vite, MapLibre GL, TanStack Query). With the API
running on port 8000:

```bash
cd frontend
npm install
npm run dev                        # http://localhost:5173, proxies /api to the API
npm test && npm run typecheck      # unit tests and type check
npm run build                      # static files in frontend/dist
```

`API_URL` points the dev proxy at another API address. A built copy served elsewhere reads
`VITE_API_URL` at build time. `VITE_MAP_STYLE` swaps the basemap, which defaults to CARTO's
free Dark Matter style (no key needed).

What it does:

- **Now**: where a visit starts. The newest week of data: how current each source is
  (GDELT nightly, UCDP's monthly Candidate files about three weeks behind), the week's
  totals against the week before, fighting in the news (GDELT, most reported first, one
  line per place, with the article), the deadliest events in UCDP's newest month, the
  countries whose risk rose most in the newest week with counted deaths, and the busiest
  countries. The map rings events from the newest two days, and **Latest** on the timeline
  moves the window back to the newest data from anywhere.
- **Map**: the events inside the time window and map view. Orange is violence, blue is
  signals, size is deaths, and older events in the window fade. Events located only to a
  country are hollow. When more than 15,000 events match, the map shows density circles
  coloured by the share that are violent; zooming in or shortening the window breaks
  them into single events.
- **Timeline**: violent events, signal events and deaths over time, each on its own scale.
  Drag the window to move it, drag its edges to resize it, click elsewhere to jump, or
  use the arrow keys (Shift resizes). Play steps the window forward. Under "More options",
  the timeline can count everywhere instead of only the map view, "Zoom timeline"
  narrows it around the window, and a table view shows the same numbers.
- **Filters**: violence or signals, and country; sources and event types are under "More
  filters". They apply to everything on the page. The URL keeps the whole view, so a
  link reopens it.
- **Getting started**: a short welcome and a six-step tour cover the essentials only.
  "Things to try" over the map then suggests one feature at a time (open an event, move
  through time, filters, risk, stories, boards, an account) and ticks each off on first
  use. Less used controls wait behind "More" toggles that stay open once opened. Watchlist,
  Tasks and Saved tabs appear once there is an account to keep them.
- **Overview**: totals for the window compared with the window before it, the deadliest
  events, and the busiest countries (click one to filter and zoom to it).
- **Event details**: click a point for its date, place, actors, deaths and source, plus
  the reports from other sources linked to it.
- **Risk**: on the Risk tab the map shows each country's weekly risk score for the end of
  the time window instead of events (larger and brighter is higher; an orange ring is a
  surge alarm), so playback shows scores changing. Clicking a country explains its score.
- **Watchlist**: save the map view or a country. Each card shows its history and how the
  current window compares with the previous one.
- **Analyst tasks**: follow-up work, linked to an event or a watched place, with
  priority, status and notes.
- **Stories**: guided starting points (Ukraine 2022, Syria, Bosnia, Afghanistan, Gaza)
  that fly to the place and play its timeline. They're under "Stories & help".
- **Boards**: paste a news article or name a topic. A link board then suggests the
  places, groups and events it connects to, each with a reason and source, to accept or
  reject. The board grows on the map as the timeline plays, and opens as a briefing on
  the 3D globe. See [Link boards](#link-boards).

## Link boards

Paste an article (or name a topic) and the backend drafts a link-analysis board:
- **What's in it:** the places and armed groups the article names, matched to the events
  data, plus GDELT events coded from the article itself.
- **When:** nearby events in the weeks before, and the deadliest earlier violence at
  those places.
- **Live data:** recorded military flights and fires nearby.

Every link carries its rule, evidence, source and a confidence, and starts as a
suggestion. The Boards tab is where an analyst reviews it. The board then plays as a
briefing on a fork of [gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view), a
3D globe, one shot per time step, ending on live military flights for recent stories.

```bash
python -m app.live adsb            # record military flights (adsb.lol) for boards' history
```

Claude reads articles when `ANTHROPIC_API_KEY` is set (`pip install -e ".[ai]"`).
Without it, a gazetteer built from the events data finds the places and groups. The
[link boards guide](docs/link-boards.md) covers running the globe, the rules, the export
and the limits.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /events` | Filter by `source`, `country`, `event_type` (repeatable), `violent`, `conflict_id`, `start`, `end`, `bbox`; duplicates hidden unless `include_duplicates=true`; `sort=fatalities` for deadliest first, `sort=reports` for most reported |
| `GET /events/{id}` | One event with the reports linked to it |
| `GET /timeline` | Violent events, signal events and deaths per `day`, `week` or `month`, same filters |
| `GET /map` | GeoJSON for the map, same filters: points up to `max_points`, otherwise counts per grid cell of `cell` degrees |
| `GET /summary` | Violent events, signal events and deaths, same filters |
| `GET /countries` | Busiest countries under the filters, with where most of their events are |
| `GET /facets` | Sources (each with its own date range, to show how current it is), event types, countries and date range in the data, for filter controls |
| `GET/POST /watchlist`, `PATCH/DELETE /watchlist/{id}` | Countries or areas (`bbox`) to watch |
| `GET/POST /tasks`, `PATCH/DELETE /tasks/{id}` | Analyst tasks, optionally linked to an event or watch item; filter by `status`, `event_id`, `watch_item_id` |
| `GET /features/cells` | Cell-month features for one `month`, filtered by `iso3` or `bbox`, with each cell's prior-year country indicators |
| `GET /indicators` | Country-year values, filtered by `iso3`, `source`, `indicator`, `start_year`, `end_year` |
| `GET /indicators/catalog` | Loaded indicators, what they measure, and the years and countries they cover |
| `GET /risk` | Every country's risk score in one `week` (any day in it; latest if left out), with its four parts and change since the week before; `sort=score`, `rise` or `fall` |
| `GET /risk/{iso3}` | One country's weekly scores and parts between `start` and `end` |
| `GET /risk/{iso3}/weeks/{week}` | Why a country scored what it did that week: each part's change with an explanation, the week's deadliest events, and its neighbours |
| `POST /ingest/{source}` | Upload a CSV or zip (`ucdp`, `acled`, `gdelt`, `wdi`, `vdem` or `epr`) |
| `GET /ingest-runs` | Counts for each load |
| `GET /ingest-runs/{id}/rejected` | Rejected rows with reasons |
| `GET /health` | Database check |
| `GET/POST /boards`, `GET/PATCH/DELETE /boards/{id}` | Link boards: list, create empty, read with nodes and links, rename, delete |
| `POST /boards/draft` | Draft a board from an article `url` or pasted `text` (optional `title`, `published`, `lookback_days`, `extractor`) |
| `POST /boards/topic` | Draft a board from a `topic`: recent coverage from GDELT's article search, each article linked like a pasted one |
| `POST /boards/{id}/review` | Accept or reject many `node_ids` and `link_ids` at once |
| `PATCH /boards/{id}/nodes/{node_id}`, `PATCH /boards/{id}/links/{link_id}` | Accept, reject or relabel one item (rejecting a node rejects its links; accepting a link accepts its ends) |
| `POST /boards/{id}/nodes`, `POST /boards/{id}/links` | Add an event (`event_id`) or a note at a point; draw a link with a reason |
| `POST /boards/{id}/nodes/{node_id}/expand` | Suggest more connections around one item |
| `GET /boards/{id}/geojson` | The board for the map; each feature has `day` for time filtering |
| `GET /boards/{id}/bundle` | A `.gevbundle.json` for gods-eye-view's Scenes > IMPORT (`include=accepted` or `all`) |
| `GET /boards/{id}/scene.json`, `GET /scene-packs/boards/{id}/{include}/{n}.geojson` | The same scene with its packs served live, for the fork's `conflict-map` source |
