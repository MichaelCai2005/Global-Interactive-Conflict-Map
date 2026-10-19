import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingest.loader import PARSERS, ingest_file
from app.models import IngestRun, RejectedRecord
from app.schemas import IngestRunOut, RejectedRecordOut

router = APIRouter(tags=["ingest"])
Db = Annotated[Session, Depends(get_db)]


@router.post("/ingest/{source}", response_model=IngestRunOut, status_code=201)
def upload(source: str, file: UploadFile, db: Db):
    """Loads an uploaded CSV or .zip from a supported source. Large files belong in the CLI."""
    if source not in PARSERS:
        raise HTTPException(404, f"unknown source, expected one of {sorted(PARSERS)}")
    filename = Path(file.filename or "upload.csv").name
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        with path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        run = ingest_file(db, source, path, filename=filename)
    if run.status != "succeeded":
        raise HTTPException(422, {"ingest_run_id": run.id, "error": run.error})
    return run


@router.get("/ingest-runs", response_model=list[IngestRunOut])
def list_runs(db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return db.scalars(select(IngestRun).order_by(IngestRun.id.desc()).limit(limit)).all()


@router.get("/ingest-runs/{run_id}/rejected", response_model=list[RejectedRecordOut])
def rejected_rows(
    run_id: int,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if db.get(IngestRun, run_id) is None:
        raise HTTPException(404, "ingest run not found")
    return db.scalars(
        select(RejectedRecord)
        .where(RejectedRecord.ingest_run_id == run_id)
        .order_by(RejectedRecord.row_number)
        .limit(limit)
        .offset(offset)
    ).all()
