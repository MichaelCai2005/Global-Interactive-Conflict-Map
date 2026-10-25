import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import make_url, text
from sqlalchemy.orm import Session

from app import auth
from app.api import board_items, boards, events, features, ingest, maps, risk, searches, workspace
from app.config import get_settings
from app.db import get_db, get_engine
from app.publish import licence_problems
from app.security import guard_writes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# The password docker-compose.yml and .env.example use for a local database.
DEV_PASSWORD = "conflict"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # A public deployment must not serve ACLED data (its license forbids it), so refuse to
    # start rather than find out from the map. `python -m app.publish copy` leaves it out.
    settings = get_settings()
    if settings.public_mode:
        with get_engine().connect() as conn:
            if problems := licence_problems(conn):
                raise RuntimeError(
                    f"PUBLIC_MODE is on but the database holds {', '.join(problems)}"
                )
        # The development password is in this repo, so a public site must get its own
        # DATABASE_URL from the host's secret store.
        if make_url(settings.database_url).password == DEV_PASSWORD:
            raise RuntimeError("PUBLIC_MODE is on but DATABASE_URL uses the development password")
    yield


app = FastAPI(
    title="Conflict Atlas API",
    description="Conflict events from UCDP and ACLED and news signals from GDELT, cleaned and linked.",
    version="0.1.0",
    lifespan=lifespan,
    # Reads are open; writes need a sign-in or ADMIN_TOKEN (see app.security).
    dependencies=[Depends(guard_writes)],
)
# Map layers and timelines are large JSON documents that compress about tenfold.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(events.router)
app.include_router(maps.router)
app.include_router(workspace.router)
app.include_router(features.router)
app.include_router(risk.router)
app.include_router(ingest.router)
app.include_router(boards.router)
app.include_router(board_items.router)
app.include_router(auth.router)
app.include_router(searches.router)
# Other sites that call this API: the gods-eye-view globe loads board scenes, and the
# frontend on GitHub Pages does everything, signing in with a bearer token rather than a
# cookie (app.auth), so no credentials mode is needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health", tags=["meta"])
def health(db: Annotated[Session, Depends(get_db)]):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
