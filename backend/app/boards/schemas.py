from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

Status = Literal["suggested", "accepted", "rejected"]
NodeKind = Literal[
    "article", "place", "actor", "claim", "event", "flight", "fire", "vessel", "note", "link"
]
# Kinds a person adds by hand: notes (ideas, pictures) and links to other pages.
UserKind = Literal["note", "link"]
UPLOADED_IMAGE = "/boards/images/"


def _web_link(value: str | None) -> str | None:
    """Links open in a new tab from the board, so only web pages are allowed."""
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not value.lower().startswith(("http://", "https://")):
        raise ValueError("Links must start with http:// or https://")
    return value


def _image_link(value: str | None) -> str | None:
    if value is not None and value.strip().startswith(UPLOADED_IMAGE):
        rest = value.strip().removeprefix(UPLOADED_IMAGE)
        if not rest.isdigit():
            raise ValueError("Not an uploaded picture")
        return value.strip()
    return _web_link(value)


WebLink = Annotated[str | None, AfterValidator(_web_link)]
ImageLink = Annotated[str | None, AfterValidator(_image_link)]


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


class ArticleIn(DraftIn):
    """Add another article to an open board, optionally at a spot on the canvas."""

    board_x: float | None = None
    board_y: float | None = None


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
    board_x: float | None
    board_y: float | None
    image_url: str | None


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


def _both_or_neither(model, a: str, b: str, what: str) -> None:
    if (getattr(model, a) is None) != (getattr(model, b) is None):
        raise ValueError(f"Give both {what} or neither")


class NodeIn(BaseModel):
    """Add a node by hand: an event from the database, or a note or link card. A card
    needs a label; a place on the map and a spot on the canvas are optional."""

    event_id: int | None = None
    kind: UserKind = "note"
    label: str | None = Field(None, min_length=1, max_length=500)
    detail: str = Field("", max_length=20000)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    time_start: datetime | None = None
    source_name: str | None = Field(None, max_length=300)
    source_url: WebLink = None
    image_url: ImageLink = None
    board_x: float | None = None
    board_y: float | None = None

    @model_validator(mode="after")
    def need_label(self):
        if self.event_id is None and not (self.label and self.label.strip()):
            raise ValueError("Give an event_id, or a label")
        _both_or_neither(self, "latitude", "longitude", "latitude and longitude")
        _both_or_neither(self, "board_x", "board_y", "board_x and board_y")
        return self


class NodePatch(BaseModel):
    """Change a card. Send a field as null to clear it (a picture, a link, a map place)."""

    status: Status | None = None
    label: str | None = Field(None, min_length=1, max_length=500)
    detail: str | None = Field(None, max_length=20000)
    source_url: WebLink = None
    image_url: ImageLink = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    time_start: datetime | None = None
    board_x: float | None = None
    board_y: float | None = None

    @model_validator(mode="after")
    def pairs(self):
        sent = self.model_fields_set
        for a, b in (("latitude", "longitude"), ("board_x", "board_y")):
            if (a in sent) != (b in sent):
                raise ValueError(f"Send {a} and {b} together")
            if a in sent:
                _both_or_neither(self, a, b, f"{a} and {b}")
        for field in ("status", "label", "detail"):
            if field in sent and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be cleared")
        return self


class LinkIn(BaseModel):
    from_node_id: int
    to_node_id: int
    reason: str = Field("", max_length=1000)


class LinkPatch(BaseModel):
    status: Status | None = None
    reason: str | None = Field(None, max_length=1000)


class Position(BaseModel):
    id: int
    x: float
    y: float


class LayoutIn(BaseModel):
    """Where cards sit on the canvas, saved after a drag or a tidy-up."""

    positions: list[Position] = Field(..., max_length=2000)


class ImageOut(BaseModel):
    id: int
    url: str
    content_type: str
    size_bytes: int


class ReviewIn(BaseModel):
    """Accept or reject many items at once."""

    status: Status
    node_ids: list[int] = []
    link_ids: list[int] = []
