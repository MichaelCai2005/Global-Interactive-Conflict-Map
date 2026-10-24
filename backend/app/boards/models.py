from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.models  # noqa: F401  (registers events, which board_nodes refers to)
from app.db import Base

# Like events, observations have a generated `geog` column with a GiST index (migration
# 0006) that only SQL reads.


class Observation(Base):
    """One recorded position from a live feed: an aircraft, a fire detection or a ship."""

    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("source", "external_id", "observed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    # The feed's own identity for the thing observed, e.g. an aircraft's ICAO hex code.
    external_id: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    label: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Board(Base):
    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    origin: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(Text)
    anchor_date: Mapped[date | None] = mapped_column(Date)
    extractor: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Whose board it is (app.auth). Boards without one are shared: anyone may read them,
    # and only the shared workspace (a local install, or the admin token) may change them.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    nodes: Mapped[list["BoardNode"]] = relationship(
        back_populates="board", cascade="all, delete-orphan", order_by="BoardNode.id"
    )
    links: Mapped[list["BoardLink"]] = relationship(
        back_populates="board", cascade="all, delete-orphan", order_by="BoardLink.id"
    )


class BoardNode(Base):
    __tablename__ = "board_nodes"
    __table_args__ = (UniqueConstraint("board_id", "key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(Integer, ForeignKey("boards.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="")
    event_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="SET NULL")
    )
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    geo_basis: Mapped[str | None] = mapped_column(String(16))
    time_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_name: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quote: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="suggested")
    created_by: Mapped[str] = mapped_column(String(16))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Where the card sits on the board canvas, once someone has moved it (migration 0008).
    board_x: Mapped[float | None] = mapped_column(Float)
    board_y: Mapped[float | None] = mapped_column(Float)
    # A picture on the card: a public link, or /boards/images/<id> for an uploaded one.
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    board: Mapped[Board] = relationship(back_populates="nodes")


class BoardLink(Base):
    __tablename__ = "board_links"
    __table_args__ = (UniqueConstraint("board_id", "from_node_id", "to_node_id", "rule"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(Integer, ForeignKey("boards.id", ondelete="CASCADE"))
    from_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board_nodes.id", ondelete="CASCADE")
    )
    to_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board_nodes.id", ondelete="CASCADE")
    )
    rule: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="suggested")
    created_by: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    board: Mapped[Board] = relationship(back_populates="links")


class BoardImage(Base):
    """A picture uploaded to a board, served at /boards/images/<id>."""

    __tablename__ = "board_images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(Integer, ForeignKey("boards.id", ondelete="CASCADE"))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
