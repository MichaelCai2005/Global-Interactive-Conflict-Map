"""The analyst's own records: areas on the watchlist and follow-up tasks."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AnalystTask, Event, WatchItem
from app.schemas import (
    Status,
    TaskIn,
    TaskOut,
    TaskPatch,
    WatchItemIn,
    WatchItemOut,
    WatchItemPatch,
)

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]


def found[T](db: Session, model: type[T], id_: int, name: str) -> T:
    row = db.get(model, id_)
    if row is None:
        raise HTTPException(404, f"{name} not found")
    return row


@router.get("/watchlist", response_model=list[WatchItemOut], tags=["watchlist"])
def list_watch_items(db: Db):
    return db.scalars(select(WatchItem).order_by(WatchItem.id)).all()


@router.post("/watchlist", response_model=WatchItemOut, status_code=201, tags=["watchlist"])
def create_watch_item(body: WatchItemIn, db: Db):
    item = WatchItem(**body.model_dump())
    db.add(item)
    db.commit()
    return item


@router.patch("/watchlist/{item_id}", response_model=WatchItemOut, tags=["watchlist"])
def update_watch_item(item_id: int, body: WatchItemPatch, db: Db):
    item = found(db, WatchItem, item_id, "watch item")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    return item


@router.delete("/watchlist/{item_id}", status_code=204, tags=["watchlist"])
def delete_watch_item(item_id: int, db: Db):
    db.delete(found(db, WatchItem, item_id, "watch item"))
    db.commit()
    return Response(status_code=204)


@router.get("/tasks", response_model=list[TaskOut], tags=["tasks"])
def list_tasks(
    db: Db,
    status: Annotated[list[Status] | None, Query()] = None,
    event_id: int | None = None,
    watch_item_id: int | None = None,
):
    query = select(AnalystTask)
    if status:
        query = query.where(AnalystTask.status.in_(status))
    if event_id is not None:
        query = query.where(AnalystTask.event_id == event_id)
    if watch_item_id is not None:
        query = query.where(AnalystTask.watch_item_id == watch_item_id)
    return db.scalars(query.order_by(AnalystTask.id.desc())).all()


@router.post("/tasks", response_model=TaskOut, status_code=201, tags=["tasks"])
def create_task(body: TaskIn, db: Db):
    if body.event_id is not None:
        found(db, Event, body.event_id, "event")
    if body.watch_item_id is not None:
        found(db, WatchItem, body.watch_item_id, "watch item")
    task = AnalystTask(**body.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut, tags=["tasks"])
def update_task(task_id: int, body: TaskPatch, db: Db):
    task = found(db, AnalystTask, task_id, "task")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", status_code=204, tags=["tasks"])
def delete_task(task_id: int, db: Db):
    db.delete(found(db, AnalystTask, task_id, "task"))
    db.commit()
    return Response(status_code=204)
