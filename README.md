# Global Interactive Conflict Map

A system for studying how conflicts emerge: it pulls together records of past violence and
the news signals that came before it (protests, threats, troop movements), cleans and links
them, and serves them through an API that a map dashboard and, later, an AI analyst can use.

## Roadmap

1. **Data pipeline and API** (this stage): load two differently formatted sources, clean,
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
| [GDELT 1.0 / 2.0 events](https://www.gdeltproject.org/data.html) | Machine-coded news events (CAMEO), 1979 onward | Tab-separated, no header, 57/58/61 columns | Signals before and around violence |

Planned next: ACLED (needs a free account), and social media. X's API charges for read
access, so Telegram channels or Bluesky are likely better first social sources.

## How the pipeline handles messy data

Every row ends up in exactly one bucket, and each ingest run records the counts:

- **Filtered out**: valid but out of scope. GDELT cooperation events (CAMEO roots 01-12)
  are dropped; only conflictual roots 13-20 are kept.
- **Rejected**: stored in `rejected_records` with the raw row and every reason it failed:
  missing or unparseable fields, coordinates out of range or at 0,0, dates in the future or
  before 1946, end date before start date, fatalities not ordered low <= best <= high, no
  usable location.
- **Merged in file**: duplicates within a file. UCDP rows share an event id; GDELT rows
  share a fingerprint (date, CAMEO code, both actors, location rounded to ~100 m), because
  GDELT writes one row per article about the same incident.
- **Inserted / updated**: upserted on `(source, dedupe_key)`, so reloading a file is
  safe. A newer UCDP release overwrites revised events; a GDELT incident seen again keeps
  its highest mention count.
- **Cross-source duplicates**: a violent event from a lower-priority source within 25 km
  and 1 day of one from a higher-priority source is linked to it in `event_links` and marked
  `duplicate_of_id`. Country-level locations are never linked, since a country centroid says
  nothing about where something happened. Priority is UCDP over GDELT.

All events share one schema: date range, `event_type`, `is_violent` (violence vs signal),
location with precision (`exact`, `admin`, `country`), actors, fatalities, report count,
tone, and source-specific extras in `attributes`.

## Running it

With Docker:

```bash
docker compose up --build          # API on http://localhost:8000, docs at /docs
docker compose exec api python -m app.ingest download gdelt --start 2022-02-01 --end 2022-02-28
docker compose exec api python -m app.ingest download ucdp --version 25.1
docker compose exec api python -m app.ingest load gdelt data/gdelt/*.zip
docker compose exec api python -m app.ingest load ucdp data/ucdp/ged251-csv.zip
```

Load UCDP and GDELT in either order; linking runs after every load. Check the current
UCDP release number on its downloads page.

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

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /events` | Filter by `source`, `country`, `event_type` (repeatable), `violent`, `conflict_id`, `start`, `end`, `bbox`; duplicates hidden unless `include_duplicates=true` |
| `GET /events/{id}` | One event with the reports linked to it |
| `GET /timeline` | Violent events, signal events and deaths per `day`, `week` or `month`, same filters |
| `POST /ingest/{source}` | Upload a CSV or zip (`ucdp` or `gdelt`) |
| `GET /ingest-runs` | Counts for each load |
| `GET /ingest-runs/{id}/rejected` | Rejected rows with reasons |
| `GET /health` | Database check |
