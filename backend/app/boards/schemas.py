from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["suggested", "accepted", "rejected"]
NodeKind = Literal[
    "article", "place", "actor", "claim", "event", "flight", "fire", "vessel", "note"
]


class DraftIn(BaseModel):
    """Start a board from an article: give its link, or paste its text (or both)."""

    url: str | None = Field(None, description="Article link; fetched unless text is given")
    text: str | None = Field(None, description="Pasted article text, for paywalled sites")
    title: str | None = None
    published: date | None = Field(None, description="The day the story is about")
    lookback_days: int = Field(60, ge=1, le=730)
    extractor: Literal["auto", "claude", "gazetteer"] | None = None

    @model_validator(mode="after")
    def need_article(self):
        if not (self.url or (self.text and self.text.strip())):
            raise ValueError("Give an article url or paste its text")
        return self


class TopicIn(BaseModel):
    """Start a board from a topic: recent news coverage plus the events data."""

    topic: str = Field(..., min_length=3, max_length=300)
    days: int = Field(14, ge=1, le=90, description="How far back to look for coverage")
    articles: int = Field(8, ge=1, le=25, description="How many articles to read")
    extractor: Literal["auto", "claude", "gazetteer"] | None = None


class BoardIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    anchor_date: date | None = None
    notes: str = ""


class BoardPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    notes: str | None = None
    anchor_date: date | None = None


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    kind: str
    label: str
    detail: str
    event_id: int | None
    latitude: float | None
    longitude: float | None
    geometry: dict[str, Any] | None
    geo_basis: str | None
    time_start: datetime | None
    time_end: datetime | None
    source_name: str | None
    source_url: str | None
    retrieved_at: datetime | None
    quote: str | None
    status: str
    created_by: str
    attributes: dict[str, Any]


class LinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_node_id: int
    to_node_id: int
    rule: str
    reason: str
    evidence: dict[str, Any]
    confidence: float
    status: str
    created_by: str


class BoardSummary(BaseModel):
    id: int
    title: str
    origin: str
    source_url: str | None
    anchor_date: date | None
    extractor: str | None
    created_at: datetime
    updated_at: datetime
    nodes: int
    links: int
    accepted: int


class BoardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    origin: str
    prompt: str
    source_url: str | None
    anchor_date: date | None
    extractor: str | None
    notes: str
    created_at: datetime
    updated_at: datetime
    nodes: list[NodeOut]
    links: list[LinkOut]


class NodeIn(BaseModel):
    """Add a node by hand: an event from the database, or a note at a place."""

    event_id: int | None = None
    kind: NodeKind = "note"
    label: str | None = Field(None, max_length=500)
    detail: str = ""
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    time_start: datetime | None = None
    source_name: str | None = None
    source_url: str | None = None

    @model_validator(mode="after")
    def need_place(self):
        if self.event_id is None and (
            self.label is None or self.latitude is None or self.longitude is None
        ):
            raise ValueError("Give an event_id, or a label with latitude and longitude")
        return self


class NodePatch(BaseModel):
    status: Status | None = None
    label: str | None = Field(None, min_length=1, max_length=500)
    detail: str | None = None


class LinkIn(BaseModel):
    from_node_id: int
    to_node_id: int
    reason: str = Field(..., min_length=1, max_length=1000)


class LinkPatch(BaseModel):
    status: Status


class ReviewIn(BaseModel):
    """Accept or reject many items at once."""

    status: Status
    node_ids: list[int] = []
    link_ids: list[int] = []
