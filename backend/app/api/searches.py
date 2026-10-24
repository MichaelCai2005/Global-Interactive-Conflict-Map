"""Saved searches: map views and board topics a person keeps to reopen.

A map view's params are the dashboard's address-bar query (`{"query": "from=...&..."}`),
so the frontend restores one exactly as it would a shared link. A topic's params are the
TopicIn it ran with; app.api.boards records each topic search as it runs, so they also
work as a history.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import Owner, Workspace
from app.db import get_db
from app.models import SavedSearch

router = APIRouter(prefix="/searches", tags=["searches"])
Db = Annotated[Session, Depends(get_db)]
Kind = Literal["map", "topic"]
# Enough for anyone's real use; stops one account filling the database.
MAX_PER_OWNER = 500


class SearchIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    kind: Kind
    params: dict[str, Any] = Field(default_factory=dict)


class SearchPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    params: dict[str, Any] | None = None
    # Marks it as just used, so it sorts first.
    used: bool = False


class SearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: Kind
    params: dict[str, Any]
    created_at: datetime
    last_used_at: datetime | None


def _found(db: Session, search_id: int, owner: Workspace) -> SavedSearch:
    row = db.get(SavedSearch, search_id)
    if row is None or not owner.owns(row):
        raise HTTPException(404, "Saved search not found")
    return row


def _make_room(db: Session, owner: Workspace) -> None:
    count = db.scalar(
        select(func.count()).select_from(SavedSearch).where(owner.where(SavedSearch.user_id))
    )
    if count >= MAX_PER_OWNER:
        raise HTTPException(409, f"You can keep up to {MAX_PER_OWNER} searches; delete some first")


def record_topic(db: Session, owner: Workspace, params: dict[str, Any]) -> None:
    """Remembers a topic search that just ran: the same topic again moves to the top."""
    topic = str(params.get("topic", "")).strip()
    row = db.scalar(
        select(SavedSearch).where(
            owner.where(SavedSearch.user_id),
            SavedSearch.kind == "topic",
            func.lower(SavedSearch.name) == topic.lower()[:200],
        )
    )
    if row is None:
        _make_room(db, owner)
        row = SavedSearch(user_id=owner.user_id, name=topic[:200], kind="topic")
        db.add(row)
    row.params = params
    row.last_used_at = datetime.now(UTC)


@router.get("", response_model=list[SearchOut])
def list_searches(db: Db, owner: Owner, kind: Annotated[Kind | None, Query()] = None):
    query = select(SavedSearch).where(owner.where(SavedSearch.user_id))
    if kind:
        query = query.where(SavedSearch.kind == kind)
    order = func.coalesce(SavedSearch.last_used_at, SavedSearch.created_at).desc()
    return db.scalars(query.order_by(order, SavedSearch.id.desc())).all()


@router.post("", response_model=SearchOut, status_code=201)
def create_search(body: SearchIn, db: Db, owner: Owner):
    _make_room(db, owner)
    row = SavedSearch(user_id=owner.user_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/{search_id}", response_model=SearchOut)
def update_search(search_id: int, body: SearchPatch, db: Db, owner: Owner):
    row = _found(db, search_id, owner)
    if body.name is not None:
        row.name = body.name
    if body.params is not None:
        row.params = body.params
    if body.used:
        row.last_used_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{search_id}", status_code=204)
def delete_search(search_id: int, db: Db, owner: Owner):
    db.delete(_found(db, search_id, owner))
    db.commit()
    return Response(status_code=204)
