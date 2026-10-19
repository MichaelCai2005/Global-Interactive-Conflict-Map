import logging
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import events, features, ingest, maps, risk, workspace
from app.db import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="Global Interactive Conflict Map API",
    description="Conflict events from UCDP and ACLED and news signals from GDELT, cleaned and linked.",
    version="0.1.0",
)
# Map layers and timelines are large JSON documents that compress about tenfold.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(events.router)
app.include_router(maps.router)
app.include_router(workspace.router)
app.include_router(features.router)
app.include_router(risk.router)
app.include_router(ingest.router)


@app.get("/health", tags=["meta"])
def health(db: Annotated[Session, Depends(get_db)]):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
