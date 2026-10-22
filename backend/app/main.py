import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import boards, events, features, ingest, maps, risk, workspace
from app.config import get_settings
from app.db import get_db, get_engine
from app.publish import licence_problems
from app.security import guard_writes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # A public deployment must not serve ACLED data (its license forbids it), so refuse to
    # start rather than find out from the map. `python -m app.publish copy` leaves it out.
    if get_settings().public_mode:
        with get_engine().connect() as conn:
            if problems := licence_problems(conn):
                raise RuntimeError(
                    f"PUBLIC_MODE is on but the database holds {', '.join(problems)}"
                )
    yield


app = FastAPI(
    title="Global Interactive Conflict Map API",
    description="Conflict events from UCDP and ACLED and news signals from GDELT, cleaned and linked.",
    version="0.1.0",
    lifespan=lifespan,
    # Reads are open; writes need ADMIN_TOKEN when one is set (see app.security).
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
# The gods-eye-view globe loads board scenes from this API, from its own origin. It only
# reads, so only GET is allowed across origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["GET"],
)


@app.get("/health", tags=["meta"])
def health(db: Annotated[Session, Depends(get_db)]):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
