from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The events table also has a generated `geog geography(Point, 4326)` column and a GiST
# index on it (see the initial migration). It is derived from latitude/longitude, so the
# ORM never writes it; spatial queries use it through SQL.


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    filtered_out: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    merged_in_file: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    cross_source_links: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("source", "dedupe_key", name="uq_events_source_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    source_event_id: Mapped[str] = mapped_column(String(64))
    # What makes two rows from the same source "the same event". For UCDP this is the
    # event id; for GDELT it is a fingerprint, because GDELT emits one row per article.
    dedupe_key: Mapped[str] = mapped_column(String(255))
    event_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    is_violent: Mapped[bool] = mapped_column(Boolean)
    country: Mapped[str | None] = mapped_column(String(128), index=True)
    admin1: Mapped[str | None] = mapped_column(String(128))
    location_name: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    geo_precision: Mapped[str] = mapped_column(String(16))
    actor1: Mapped[str | None] = mapped_column(Text)
    actor2: Mapped[str | None] = mapped_column(Text)
    fatalities_best: Mapped[int | None] = mapped_column(Integer)
    fatalities_low: Mapped[int | None] = mapped_column(Integer)
    fatalities_high: Mapped[int | None] = mapped_column(Integer)
    report_count: Mapped[int] = mapped_column(Integer, default=1)
    tone: Mapped[float | None] = mapped_column(Float)
    source_url: Mapped[str | None] = mapped_column(Text)
    conflict_id: Mapped[str | None] = mapped_column(String(64), index=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    ingest_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("ingest_runs.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventLink(Base):
    __tablename__ = "event_links"
    __table_args__ = (UniqueConstraint("event_id", "related_event_id", "link_type"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"))
    related_event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    link_type: Mapped[str] = mapped_column(String(32))
    distance_km: Mapped[float] = mapped_column(Float)
    day_gap: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)


class RejectedRecord(Base):
    __tablename__ = "rejected_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ingest_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingest_runs.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32))
    row_number: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[list[str]] = mapped_column(ARRAY(Text))
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
