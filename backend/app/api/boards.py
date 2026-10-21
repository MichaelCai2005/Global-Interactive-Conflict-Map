"""Link boards: draft one from an article or topic, review it, export it to the globe."""

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.boards import draft, export, rules, topic
from app.boards.articles import Article, ArticleError, fetch_article
from app.boards.extract import ExtractionError, GazetteerExtractor, get_extractor
from app.boards.models import Board, BoardLink, BoardNode
from app.boards.schemas import (
    BoardIn,
    BoardOut,
    BoardPatch,
    BoardSummary,
    DraftIn,
    LinkIn,
    LinkOut,
    LinkPatch,
    NodeIn,
    NodeOut,
    NodePatch,
    ReviewIn,
    TopicIn,
)
from app.db import get_db

log = logging.getLogger(__name__)
router = APIRouter(tags=["boards"])
Db = Annotated[Session, Depends(get_db)]
Include = Literal["accepted", "all"]


def _board(db: Session, board_id: int) -> Board:
    board = db.scalar(
        select(Board)
        .where(Board.id == board_id)
        .options(selectinload(Board.nodes), selectinload(Board.links))
    )
    if board is None:
        raise HTTPException(404, "Board not found")
    return board


def _touch(board: Board) -> None:
    board.updated_at = datetime.now(UTC)


@router.get("/boards", response_model=list[BoardSummary])
def list_boards(db: Db):
    nodes = (
        select(
            BoardNode.board_id,
            func.count().label("n"),
            func.count().filter(BoardNode.status == "accepted").label("a"),
        )
        .group_by(BoardNode.board_id)
        .subquery()
    )
    links = (
        select(BoardLink.board_id, func.count().label("n")).group_by(BoardLink.board_id).subquery()
    )
    rows = db.execute(
        select(Board, nodes.c.n, nodes.c.a, links.c.n)
        .outerjoin(nodes, nodes.c.board_id == Board.id)
        .outerjoin(links, links.c.board_id == Board.id)
        .order_by(Board.updated_at.desc())
    ).all()
    return [
        BoardSummary(
            id=b.id,
            title=b.title,
            origin=b.origin,
            source_url=b.source_url,
            anchor_date=b.anchor_date,
            extractor=b.extractor,
            created_at=b.created_at,
            updated_at=b.updated_at,
            nodes=n or 0,
            accepted=a or 0,
            links=k or 0,
        )
        for b, n, a, k in rows
    ]


@router.post("/boards", response_model=BoardOut, status_code=201)
def create_board(body: BoardIn, db: Db):
    board = Board(title=body.title, origin="manual", anchor_date=body.anchor_date, notes=body.notes)
    db.add(board)
    db.commit()
    return _board(db, board.id)


@router.post("/boards/draft", response_model=BoardOut, status_code=201)
def draft_board(body: DraftIn, db: Db):
    """Read an article and suggest a board: its places, actors, claims and linked events.

    Everything but the article starts as a suggestion with a reason, to accept or reject.
    """
    if body.text and body.text.strip():
        article = Article(
            text=body.text.strip(), title=body.title, url=body.url, published=body.published
        )
    else:
        try:
            article = fetch_article(body.url)
        except ArticleError as e:
            raise HTTPException(422, str(e)) from e
        article.title = body.title or article.title
    anchor = body.published or article.published or date.today()
    article.published = article.published or anchor

    extraction, extractor_name, note = _extract(db, article, anchor, body.extractor)
    board = Board(
        title=(article.title or "Untitled article")[:300],
        origin="article",
        prompt=article.text,
        source_url=article.url,
        anchor_date=anchor,
        extractor=extractor_name,
        notes=note,
    )
    db.add(board)
    db.flush()
    draft.build_from_article(
        db, board, article, extraction, anchor, draft.RuleSettings(lookback_days=body.lookback_days)
    )
    db.commit()
    return _board(db, board.id)


def _extract(db: Session, article: Article, anchor: date, kind: str | None):
    """Extract with Claude when available; fall back to the gazetteer if Claude fails."""
    try:
        extractor = get_extractor(kind)
    except ExtractionError as e:
        raise HTTPException(502, str(e)) from e
    try:
        return extractor.extract(db, article, anchor), extractor.name, ""
    except ExtractionError as e:
        if kind == "claude":
            raise HTTPException(502, str(e)) from e
        log.warning("Claude extraction failed, using the gazetteer: %s", e)
        fallback = GazetteerExtractor()
        note = f"Claude extraction failed ({e}); drafted with the gazetteer instead."
        return fallback.extract(db, article, anchor), fallback.name, note


@router.post("/boards/topic", response_model=BoardOut, status_code=201)
def topic_board(body: TopicIn, db: Db):
    """Start a board from a topic: recent coverage from GDELT's article search, read and
    linked like a pasted article. When the search is unavailable or finds nothing, the
    board starts from the topic's own words and the events data, and says so."""
    problem = None
    try:
        articles = topic.search_articles(body.topic, days=body.days, limit=body.articles)
        if not articles:
            problem = "GDELT's article search found no recent coverage"
    except topic.TopicError as e:
        articles, problem = [], str(e)
    board = None
    if articles:
        try:
            board = topic.build_topic_board(db, body, articles, _extract)
        except topic.TopicError as e:
            db.rollback()
            problem = str(e)
    if board is None:
        try:
            board = topic.build_from_words(db, body, _extract, problem or "")
        except topic.TopicError as e:
            db.rollback()
            raise HTTPException(404, f"{problem}. {e}" if problem else str(e)) from e
    db.commit()
    return _board(db, board.id)


@router.get("/boards/{board_id}", response_model=BoardOut)
def get_board(board_id: int, db: Db):
    return _board(db, board_id)


@router.patch("/boards/{board_id}", response_model=BoardOut)
def update_board(board_id: int, body: BoardPatch, db: Db):
    board = _board(db, board_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(board, field, value)
    _touch(board)
    db.commit()
    return _board(db, board_id)


@router.delete("/boards/{board_id}", status_code=204)
def delete_board(board_id: int, db: Db):
    db.delete(_board(db, board_id))
    db.commit()
    return Response(status_code=204)


@router.post("/boards/{board_id}/nodes", response_model=NodeOut, status_code=201)
def add_node(board_id: int, body: NodeIn, db: Db):
    board = _board(db, board_id)
    builder = draft.BoardBuilder(db, board)
    if body.event_id is not None:
        rows = rules.events_by_id(db, [body.event_id])
        if not rows:
            raise HTTPException(404, "Event not found")
        node = builder.event_node(rows[0])
    else:
        key = f"{body.kind}:user:{len(board.nodes) + 1}:{body.latitude:.4f}:{body.longitude:.4f}"
        node = builder.node(
            key,
            kind=body.kind,
            label=body.label,
            detail=body.detail,
            latitude=body.latitude,
            longitude=body.longitude,
            geo_basis="user",
            time_start=body.time_start,
            source_name=body.source_name,
            source_url=body.source_url,
            created_by="user",
        )
    node.status = "accepted"
    node.created_by = "user"
    _touch(board)
    db.commit()
    return node


@router.patch("/boards/{board_id}/nodes/{node_id}", response_model=NodeOut)
def update_node(board_id: int, node_id: int, body: NodePatch, db: Db):
    board = _board(db, board_id)
    node = next((n for n in board.nodes if n.id == node_id), None)
    if node is None:
        raise HTTPException(404, "Node not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(node, field, value)
    if body.status == "rejected":
        # A rejected node takes its links with it; an accepted link needs both ends.
        for k in board.links:
            if node_id in (k.from_node_id, k.to_node_id):
                k.status = "rejected"
    _touch(board)
    db.commit()
    return node


@router.post("/boards/{board_id}/nodes/{node_id}/expand", response_model=BoardOut)
def expand(board_id: int, node_id: int, db: Db):
    """Suggest more connections around one node: nearby events, its actors, other sources'
    reports of the same incident, recorded flights and fires."""
    board = _board(db, board_id)
    node = next((n for n in board.nodes if n.id == node_id), None)
    if node is None:
        raise HTTPException(404, "Node not found")
    draft.expand_node(db, board, node)
    _touch(board)
    db.commit()
    db.expire_all()
    return _board(db, board_id)


@router.post("/boards/{board_id}/links", response_model=LinkOut, status_code=201)
def add_link(board_id: int, body: LinkIn, db: Db):
    board = _board(db, board_id)
    ids = {n.id for n in board.nodes}
    if body.from_node_id not in ids or body.to_node_id not in ids:
        raise HTTPException(422, "Both ends must be nodes on this board")
    if body.from_node_id == body.to_node_id:
        raise HTTPException(422, "A link needs two different nodes")
    existing = next(
        (
            k
            for k in board.links
            if k.rule == "user"
            and {k.from_node_id, k.to_node_id} == {body.from_node_id, body.to_node_id}
        ),
        None,
    )
    if existing:
        raise HTTPException(409, "You already linked these two")
    link = BoardLink(
        board_id=board.id,
        from_node_id=body.from_node_id,
        to_node_id=body.to_node_id,
        rule="user",
        reason=body.reason,
        evidence={},
        confidence=1.0,
        status="accepted",
        created_by="user",
    )
    board.links.append(link)
    _touch(board)
    db.commit()
    return link


@router.patch("/boards/{board_id}/links/{link_id}", response_model=LinkOut)
def update_link(board_id: int, link_id: int, body: LinkPatch, db: Db):
    board = _board(db, board_id)
    link = next((k for k in board.links if k.id == link_id), None)
    if link is None:
        raise HTTPException(404, "Link not found")
    if body.status == "accepted":
        # Accepting a link accepts both ends, so it can be shown.
        for n in board.nodes:
            if n.id in (link.from_node_id, link.to_node_id) and n.status == "suggested":
                n.status = "accepted"
    link.status = body.status
    _touch(board)
    db.commit()
    return link


@router.post("/boards/{board_id}/review", response_model=BoardOut)
def review(board_id: int, body: ReviewIn, db: Db):
    board = _board(db, board_id)
    nodes = {n.id: n for n in board.nodes}
    for node_id in body.node_ids:
        if node_id in nodes:
            nodes[node_id].status = body.status
    for k in board.links:
        if k.id in body.link_ids:
            k.status = body.status
            if body.status == "accepted":
                for end in (k.from_node_id, k.to_node_id):
                    if nodes[end].status == "suggested":
                        nodes[end].status = "accepted"
        if body.status == "rejected" and (
            k.from_node_id in body.node_ids or k.to_node_id in body.node_ids
        ):
            k.status = "rejected"
    _touch(board)
    db.commit()
    return _board(db, board_id)


# --- Map and globe ------------------------------------------------------------------


@router.get("/boards/{board_id}/geojson")
def board_geojson(board_id: int, db: Db, include: Include = "all"):
    """Nodes as points (tracks as lines) and links as straight lines, for the 2D map.

    Each feature carries `day` (days since 1970-01-01) so the map can filter by time.
    """
    board = _board(db, board_id)
    nodes, links = export.visible(board, include)
    by_id = {n.id: n for n in nodes}
    features = []
    for n in nodes:
        geometry = n.geometry or {"type": "Point", "coordinates": [n.longitude, n.latitude]}
        features.append(
            {
                "type": "Feature",
                "id": f"n{n.id}",
                "geometry": geometry,
                "properties": {
                    "node_id": n.id,
                    "kind": n.kind,
                    "label": n.label,
                    "status": n.status,
                    "style": export.node_style(n),
                    "day": _day(n.time_start),
                },
            }
        )
    for k in links:
        a, b = by_id[k.from_node_id], by_id[k.to_node_id]
        features.append(
            {
                "type": "Feature",
                "id": f"l{k.id}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[a.longitude, a.latitude], [b.longitude, b.latitude]],
                },
                "properties": {
                    "link_id": k.id,
                    "rule": k.rule,
                    "status": k.status,
                    "confidence": k.confidence,
                    "day": max(
                        (d for d in (_day(a.time_start), _day(b.time_start)) if d is not None),
                        default=None,
                    ),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _day(value: datetime | None) -> int | None:
    return None if value is None else (rules.utc_day(value) - date(1970, 1, 1)).days


@router.get("/boards/{board_id}/bundle")
def board_bundle(board_id: int, db: Db, include: Include = "accepted"):
    """A .gevbundle.json for gods-eye-view's Scenes > IMPORT, packs embedded."""
    board = _board(db, board_id)
    try:
        text = export.bundle(board, include)
    except export.ExportError as e:
        raise HTTPException(409, str(e)) from e
    return Response(
        text,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{export.filename(board)}"'},
    )


def _pack_path(board_id: int, include: str):
    return lambda step, i: f"boards/{board_id}/{include}/{i}.geojson"


@router.get("/boards/{board_id}/scene.json")
def board_scene(board_id: int, db: Db, include: Include = "accepted"):
    """A scene whose packs load live from this API, for a globe that registers the
    `conflict-map` source (docs/gods-eye-view.md). Re-export after editing the board."""
    board = _board(db, board_id)
    try:
        project, _ = export.build_scene(
            board, include, adapter="conflict-map", path_for=_pack_path(board_id, include)
        )
    except export.ExportError as e:
        raise HTTPException(409, str(e)) from e
    return project


@router.get("/scene-packs/boards/{board_id}/{include}/{index}.geojson")
def scene_pack(board_id: int, include: Include, index: int, db: Db):
    """One pack of a live scene. The path has no query string: the globe forbids them."""
    board = _board(db, board_id)
    try:
        _, files = export.build_scene(
            board, include, adapter="conflict-map", path_for=_pack_path(board_id, include)
        )
    except export.ExportError as e:
        raise HTTPException(409, str(e)) from e
    data = files.get(f"boards/{board_id}/{include}/{index}.geojson")
    if data is None:
        raise HTTPException(404, "No such pack; the board may have changed, so re-export")
    return Response(data, media_type="application/geo+json")
