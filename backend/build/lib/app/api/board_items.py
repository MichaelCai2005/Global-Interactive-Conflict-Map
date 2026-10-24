"""The board as a mood board: move cards, add articles and pictures, remove your own cards
and lines. The rest of the board API is in app.api.boards."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.boards import _board, _extract, _touch, can_read
from app.auth import Owner, Viewer
from app.boards import draft
from app.boards.articles import Article, ArticleError, fetch_article
from app.boards.models import Board, BoardImage, BoardNode
from app.boards.names import normalized_url
from app.boards.schemas import UPLOADED_IMAGE, ArticleIn, BoardOut, ImageOut, LayoutIn
from app.db import get_db

router = APIRouter(tags=["boards"])
Db = Annotated[Session, Depends(get_db)]

MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Raster formats only, told apart by their first bytes. SVG is left out on purpose: it
# can carry script, and these pictures are served from the API's own origin.
IMAGE_TYPES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}


def _sniff(data: bytes) -> str | None:
    for content_type, signatures in IMAGE_TYPES.items():
        if data.startswith(signatures):
            if content_type == "image/webp" and data[8:12] != b"WEBP":
                continue
            return content_type
    return None


@router.post("/boards/{board_id}/layout")
def save_layout(board_id: int, body: LayoutIn, db: Db, owner: Owner):
    """Save where cards sit on the canvas. It leaves the board's update time alone, so
    moving cards does not make the map reload the board."""
    board = _board(db, board_id, owner=owner)
    nodes = {n.id: n for n in board.nodes}
    missing = [p.id for p in body.positions if p.id not in nodes]
    if missing:
        raise HTTPException(422, f"Not on this board: {', '.join(map(str, missing[:5]))}")
    for p in body.positions:
        nodes[p.id].board_x, nodes[p.id].board_y = round(p.x, 1), round(p.y, 1)
    db.commit()
    return {"saved": len(body.positions)}


@router.delete("/boards/{board_id}/nodes/{node_id}", status_code=204)
def delete_node(board_id: int, node_id: int, db: Db, owner: Owner):
    """Remove a note or link card someone added. Suggested items are rejected instead,
    so the rules do not suggest them again."""
    board = _board(db, board_id, owner=owner)
    node = next((n for n in board.nodes if n.id == node_id), None)
    if node is None:
        raise HTTPException(404, "Node not found")
    if node.kind not in ("note", "link"):
        raise HTTPException(409, "Only notes and links you added can be deleted; reject it instead")
    image = node.image_url
    board.links = [k for k in board.links if node_id not in (k.from_node_id, k.to_node_id)]
    board.nodes.remove(node)
    if image and image.startswith(UPLOADED_IMAGE):
        still_used = any(n.image_url == image for n in board.nodes)
        if not still_used:
            image_id = int(image.removeprefix(UPLOADED_IMAGE))
            row = db.get(BoardImage, image_id)
            if row is not None and row.board_id == board.id:
                db.delete(row)
    _touch(board)
    db.commit()
    return Response(status_code=204)


@router.delete("/boards/{board_id}/links/{link_id}", status_code=204)
def delete_link(board_id: int, link_id: int, db: Db, owner: Owner):
    board = _board(db, board_id, owner=owner)
    link = next((k for k in board.links if k.id == link_id), None)
    if link is None:
        raise HTTPException(404, "Link not found")
    if link.rule != "user":
        raise HTTPException(409, "Only links you drew can be deleted; reject it instead")
    board.links.remove(link)
    _touch(board)
    db.commit()
    return Response(status_code=204)


@router.post("/boards/{board_id}/articles", response_model=BoardOut, status_code=201)
def add_article(board_id: int, body: ArticleIn, db: Db, owner: Owner):
    """Read another article into an open board. Places, groups and events it shares with
    the board are merged, so its links join the existing cards."""
    board = _board(db, board_id, owner=owner)
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
    wanted = normalized_url(article.url)
    if wanted and any(normalized_url(n.source_url) == wanted for n in board.nodes):
        raise HTTPException(409, "This article is already on the board")
    anchor = body.published or article.published or board.anchor_date or date.today()
    article.published = article.published or anchor

    extraction, extractor_name, note = _extract(db, article, anchor, body.extractor)
    key = f"article:added:{uuid.uuid4().hex[:12]}"
    draft.build_from_article(
        db,
        board,
        article,
        extraction,
        anchor,
        draft.RuleSettings(lookback_days=body.lookback_days),
        article_key=key,
    )
    names = {x.strip() for x in (board.extractor or "").split(",") if x.strip()}
    board.extractor = ", ".join(sorted(names | {extractor_name}))
    board.anchor_date = board.anchor_date or anchor
    if note:
        board.notes = f"{board.notes}\n{note}".strip()
    node = db.scalar(select(BoardNode).where(BoardNode.board_id == board.id, BoardNode.key == key))
    if node is not None and body.board_x is not None and body.board_y is not None:
        node.board_x, node.board_y = body.board_x, body.board_y
    _touch(board)
    db.commit()
    db.expire_all()
    return _board(db, board_id, owner=owner)


@router.post("/boards/{board_id}/images", response_model=ImageOut, status_code=201)
def upload_image(board_id: int, db: Db, file: Annotated[UploadFile, File()], owner: Owner):
    """Upload a picture for a card (PNG, JPEG, GIF or WebP, up to 5 MB). Put the returned
    url in a card's image_url."""
    board = _board(db, board_id, owner=owner)
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Pictures can be at most 5 MB")
    content_type = _sniff(data)
    if content_type is None:
        raise HTTPException(415, "Upload a PNG, JPEG, GIF or WebP picture")
    image = BoardImage(
        board_id=board.id, content_type=content_type, size_bytes=len(data), data=data
    )
    db.add(image)
    db.commit()
    return ImageOut(
        id=image.id,
        url=f"{UPLOADED_IMAGE}{image.id}",
        content_type=content_type,
        size_bytes=len(data),
    )


@router.get("/boards/images/{image_id}")
def get_image(image_id: int, db: Db, viewer: Viewer):
    """A picture, to whoever may read its board; pictures on a private board stay private."""
    image = db.get(BoardImage, image_id)
    if image is None or not can_read(db.get(Board, image.board_id), viewer):
        raise HTTPException(404, "Picture not found")
    return Response(
        image.data,
        media_type=image.content_type,
        headers={
            # An uploaded picture never changes; a new upload gets a new id.
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
