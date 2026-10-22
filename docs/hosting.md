# Putting the map online

The map has three parts to host. All three read their addresses from environment
variables, so the code doesn't change between your laptop and the web.

| Part | Where | Setting |
|---|---|---|
| Database (Postgres + PostGIS) | [Neon](https://neon.com) | — |
| API (`backend/Dockerfile`) | Render, Railway or Fly.io | `DATABASE_URL`, `PUBLIC_MODE`, `ADMIN_TOKEN`, `CORS_ORIGINS` |
| Frontend (`frontend/`, a static Vite build) | Vercel, Netlify or Cloudflare Pages | `VITE_API_URL` |

## What a public site may show

ACLED's license forbids publishing its events, so the hosted database never gets them.
`python -m app.publish copy` leaves out ACLED events, links to them and board nodes built
on them, and rebuilds the cell features and risk scores from what it copied. The API
backs this up in two ways. With `PUBLIC_MODE=true` it refuses to start if the database
holds ACLED data, and it refuses ACLED uploads even from an admin. UCDP (CC BY 4.0), GDELT
and the World Bank indicators can be republished with credit.

## 1. Create the database

1. Sign up at neon.com and create a project. Pick the region nearest your API host and
   Postgres 17, the same version you run locally.
2. On the project's dashboard, click **Connect** and copy the connection string with
   **connection pooling turned off** (the host has no `-pooler` in it). The copy needs a
   direct connection.
3. Turn it into SQLAlchemy's form by changing `postgresql://` to `postgresql+psycopg://`.
   Keep `?sslmode=require` on the end.

You don't need to create PostGIS yourself. The first migration runs
`CREATE EXTENSION postgis`, and Neon allows it on every plan.

## 2. Copy your data

Start your local Postgres, then from `backend/`:

```powershell
$env:TARGET_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST/neondb?sslmode=require"
.venv\Scripts\python -m app.publish copy
```

The command migrates the target to the current schema and streams every table across in
one transaction, so a failed copy leaves nothing half done. It then rebuilds the features
and risk scores on the target and checks it holds no ACLED data. It won't overwrite a
database that already has events unless you pass `--replace`.

On 2026-10-21 a full copy took about 4 minutes into a local database and came to 979 MB
(689k UCDP and GDELT events). `--since 2018-01-01` came to 568 MB in under 2 minutes.
Neon's free plan holds 0.5 GB per project. Its paid Launch plan has no monthly minimum,
bills storage at about $0.35 per GB-month and compute by the hour, and shuts the
database down when nobody is using it. A full copy costs well under a dollar a month to
store.

Too big for the free tier? Copy less:

- `--since 2010-01-01` copies only events from that date on.
- `--without gdelt` leaves GDELT's news-based events out.
- `--with-workspace` also copies your watchlist and tasks, which stay local by default
  because they're personal notes.

`python -m app.publish check --url <url>` lists anything in a database that a public site
must not show.

## 3. Deploy the API

On Render: **New > Web Service**, connect the GitHub repo, set the root directory to
`backend`, and choose Docker. The container runs the migrations, then starts on the port
the host gives it. Set these environment variables:

| Variable | Value |
|---|---|
| `DATABASE_URL` | The Neon URL from step 1. The API may use Neon's pooled URL instead. |
| `PUBLIC_MODE` | `true` |
| `ADMIN_TOKEN` | A long random string, e.g. from `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Leave it unset to make the site fully read-only. |
| `CORS_ORIGINS` | Your frontend's address, e.g. `https://conflict-map.vercel.app` |

Leave `ANTHROPIC_API_KEY` unset. The Docker image doesn't install the Claude extra anyway,
so boards drafted on the server use the gazetteer.

Check it: `https://<api-host>/health` should return `{"status":"ok"}`.

## 4. Deploy the frontend

On Vercel: **Add New > Project**, pick the repo, set the root directory to `frontend`, and
add `VITE_API_URL=https://<api-host>`. Leave `/api` off the end, because that prefix only
exists in the local dev proxy. Then add the frontend's address to the API's `CORS_ORIGINS`.

## 5. Keep it current

`.github/workflows/update-hosted-data.yml` runs every night. It loads yesterday's GDELT
events, rebuilds this month's features and the risk scores, prunes live observations
older than 90 days, and checks that nothing unpublishable arrived. To turn it on:

1. On GitHub, open **Settings > Secrets and variables > Actions** and add a secret named
   `HOSTED_DATABASE_URL` holding the direct Neon URL from step 1.
2. Merge the workflow to the default branch, because GitHub only runs schedules from
   there. Use **Actions > Update hosted data > Run workflow** to run it now or to load a
   given day.

New UCDP releases come out once a year. Load them locally, then run
`python -m app.publish copy --replace` again.

## Changing data on the live site

Reads are open to everyone. Every other request (uploads, boards, the watchlist and tasks)
needs the admin token:

```bash
curl -X POST https://<api-host>/boards/draft \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"url": "https://..."}'
```

With no `ADMIN_TOKEN` set, a public deployment refuses all of them. A local setup with
no token stays open, as before.
