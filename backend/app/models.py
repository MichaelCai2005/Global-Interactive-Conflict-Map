from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# The events table also has a generated `geog geography(Point, 4326)` column and a GiST
# index on it (see the initial migration). It is derived from latitude/longitude, so the
# ORM never writes it; spatial queries use it through SQL.

# PRIO-GRID numbers 0.5 degree cells row by row from the south-west corner (-180, -90),
# 720 to a row, starting at 1. Points on the north pole or the antimeridian go in the last
# row or column. Matches the priogrid_gid UCDP publishes for its events.
PRIOGRID_GID_SQL = """CASE WHEN geo_precision = 'country' THEN NULL ELSE
    LEAST(floor((latitude + 90) / 0.5), 359)::integer * 720
    + LEAST(floor((longitude + 180) / 0.5), 719)::integer + 1 END"""


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
    country_iso3: Mapped[str | None] = mapped_column(String(3), index=True)
    admin1: Mapped[str | None] = mapped_column(String(128))
    location_name: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    geo_precision: Mapped[str] = mapped_column(String(16))
    # PRIO-GRID 0.5 degree cell, derived by the database from latitude/longitude; NULL for
    # country-level locations, whose centroid says nothing about where in the country.
    priogrid_gid: Mapped[int | None] = mapped_column(Integer, Computed(PRIOGRID_GID_SQL))
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
    # When GDELT first published the event, to the quarter hour; empty for other sources.
    first_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Which of UCDP's kinds of violence a violent event is ("state_based", "non_state",
    # "one_sided"), inferred from its sides for ACLED and GDELT; NULL when unclear or not
    # violent. See app.conflict_type.
    conflict_type: Mapped[str | None] = mapped_column(String(16))
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


class GdeltId(Base):
    """Which event a GDELT GLOBALEVENTID went into, so its Mentions can find it."""

    __tablename__ = "gdelt_ids"

    global_event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="CASCADE"), index=True
    )


class EventSource(Base):
    """One news article that reported an event."""

    __tablename__ = "event_sources"
    __table_args__ = (UniqueConstraint("event_id", "url", name="uq_event_sources_event_url"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[int | None] = mapped_column(SmallInteger)


class CountryIndicator(Base):
    """One country-year value of a structural indicator, e.g. V-Dem's electoral democracy index."""

    __tablename__ = "country_indicators"
    __table_args__ = (PrimaryKeyConstraint("source", "indicator", "iso3", "year"),)

    source: Mapped[str] = mapped_column(String(32))
    indicator: Mapped[str] = mapped_column(String(64))
    iso3: Mapped[str] = mapped_column(String(3))
    year: Mapped[int] = mapped_column(SmallInteger)
    value: Mapped[float] = mapped_column(Float)
    ingest_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("ingest_runs.id"))


class CellMonth(Base):
    """Event counts and conflict-history features for one PRIO-GRID cell in one month.

    Built from the events table by app.features. Columns named *_last{N}m cover the N
    months before `month`, never `month` itself, so they can be used to predict it.
    """

    __tablename__ = "cell_month_features"
    __table_args__ = (PrimaryKeyConstraint("gid", "month"),)

    gid: Mapped[int] = mapped_column(Integer)
    month: Mapped[date] = mapped_column(Date, index=True)
    # The country most of the cell's events fall in; cells on borders pick the majority.
    iso3: Mapped[str | None] = mapped_column(String(3))
    # This month.
    ucdp_events: Mapped[int] = mapped_column(Integer)
    ucdp_fatalities: Mapped[int] = mapped_column(Integer)
    violent_events: Mapped[int] = mapped_column(Integer)
    acled_events: Mapped[int] = mapped_column(Integer)
    acled_fatalities: Mapped[int] = mapped_column(Integer)
    acled_protests: Mapped[int] = mapped_column(Integer)
    acled_riots: Mapped[int] = mapped_column(Integer)
    gdelt_threats: Mapped[int] = mapped_column(Integer)
    gdelt_protests: Mapped[int] = mapped_column(Integer)
    gdelt_force_posture: Mapped[int] = mapped_column(Integer)
    gdelt_coercion: Mapped[int] = mapped_column(Integer)
    gdelt_violence: Mapped[int] = mapped_column(Integer)
    gdelt_mentions: Mapped[int] = mapped_column(Integer)
    gdelt_tone: Mapped[float | None] = mapped_column(Float)
    # Earlier months.
    ucdp_fatalities_last1m: Mapped[int] = mapped_column(Integer)
    ucdp_fatalities_last3m: Mapped[int] = mapped_column(Integer)
    ucdp_fatalities_last12m: Mapped[int] = mapped_column(Integer)
    ucdp_fatalities_last36m: Mapped[int] = mapped_column(Integer)
    months_since_violence: Mapped[int | None] = mapped_column(Integer)
    neighbour_fatalities_last1m: Mapped[int] = mapped_column(Integer)
    neighbour_fatalities_last12m: Mapped[int] = mapped_column(Integer)
    gdelt_protests_last3m: Mapped[int] = mapped_column(Integer)
    gdelt_threats_last3m: Mapped[int] = mapped_column(Integer)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class WatchItem(Base):
    """A country or map area an analyst keeps an eye on."""

    __tablename__ = "watch_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(128))
    # min_lon,min_lat,max_lon,max_lat, the same format as the events bbox filter.
    bbox: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Whose it is; None is the shared workspace (a local install, or the admin token).
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )


class AnalystTask(Base):
    """A piece of follow-up work, optionally about one event or one watched area."""

    __tablename__ = "analyst_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open")
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    event_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    watch_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("watch_items.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[Event | None] = relationship(lazy="joined")


class RiskCountry(Base):
    """A country scored by app.risk, with where to draw it and which countries border it."""

    __tablename__ = "risk_countries"

    iso3: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    neighbours: Mapped[list[str]] = mapped_column(ARRAY(String(3)), default=list)


class RiskScore(Base):
    """One country's risk score in one week (weeks start on Monday). See app.risk."""

    __tablename__ = "risk_scores"
    __table_args__ = (PrimaryKeyConstraint("iso3", "week"),)

    iso3: Mapped[str] = mapped_column(String(3), ForeignKey("risk_countries.iso3"))
    week: Mapped[date] = mapped_column(Date)
    violent_events: Mapped[int] = mapped_column(Integer)
    deaths: Mapped[int] = mapped_column(Integer)
    gdelt_events: Mapped[int] = mapped_column(Integer)
    # Raw component values.
    history: Mapped[float] = mapped_column(Float)
    # The source whose surge z-score was larger, its violent events and its usual weekly count.
    surge_source: Mapped[str | None] = mapped_column(String(32))
    surge_events: Mapped[int | None] = mapped_column(Integer)
    surge_baseline: Mapped[float | None] = mapped_column(Float)
    surge_z: Mapped[float | None] = mapped_column(Float)
    surge: Mapped[float] = mapped_column(Float)
    spread: Mapped[float] = mapped_column(Float)
    share_z: Mapped[float | None] = mapped_column(Float)
    goldstein_z: Mapped[float | None] = mapped_column(Float)
    tone_z: Mapped[float | None] = mapped_column(Float)
    signal: Mapped[float] = mapped_column(Float)
    # What each component adds to the score; they sum to `score`.
    points_history: Mapped[float] = mapped_column(Float)
    points_surge: Mapped[float] = mapped_column(Float)
    points_spread: Mapped[float] = mapped_column(Float)
    points_signal: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    trend: Mapped[str | None] = mapped_column(String(16))
    surge_alarm: Mapped[bool] = mapped_column(Boolean)
    provisional: Mapped[bool] = mapped_column(Boolean)


class User(Base):
    """Someone with an account (app.auth). Emails are stored lower-cased."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """One signed-in browser. The cookie holds a random token; this keeps its SHA-256."""

    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    user: Mapped[User] = relationship(lazy="joined")


class SavedSearch(Base):
    """A map view or board topic kept to reopen: `params` is what the frontend needs to
    restore it (a map view's address-bar query, or a topic search's TopicIn)."""

    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
