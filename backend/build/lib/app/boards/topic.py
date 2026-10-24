"""Start a board from a topic ("Wagner in Mali") instead of one article.

GDELT's DOC 2.0 API searches the last three months of worldwide online news. The board
reads the most relevant recent articles and links each one like a pasted article, so a
topic board is several article boards merged: shared places, actors and events appear
once, with a link from every article that names them.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.boards import draft
from app.boards.articles import USER_AGENT, Article, ArticleError, fetch_article
from app.boards.extract import ExtractionError, get_extractor
from app.boards.models import Board
from app.boards.names import normalized_url
from app.boards.schemas import TopicIn

log = logging.getLogger(__name__)
DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_last_call = 0.0


class TopicError(Exception):
    pass


@dataclass
class Found:
    url: str
    title: str
    seen: date | None
    domain: str


def _get_with_retry(url: str, attempts: int = 4) -> str:
    global _last_call
    for attempt in range(attempts):
        wait = 5.2 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == attempts - 1:
                raise TopicError(f"GDELT article search failed: {e}") from e
            log.info("GDELT article search is busy; waiting before retry %d", attempt + 1)
            time.sleep(6 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise TopicError(f"GDELT article search failed: {e}") from e
    raise TopicError("GDELT article search failed")


def gdelt_query(topic: str) -> str:
    """GDELT refuses keywords under three letters unless they are inside a quoted phrase,
    so "El Fasher" is searched as a phrase. Topics with their own quotes are left alone."""
    topic = " ".join(topic.split())
    if '"' in topic:
        return topic
    if any(len(word) < 3 for word in topic.split() if word not in ("OR", "AND")):
        return f'"{topic}"'
    return topic


def search_articles(topic: str, days: int = 14, limit: int = 8) -> list[Found]:
    """The most relevant English-language articles about a topic, one per story.

    GDELT asks for at most one request every five seconds, and answers 429 when it is
    busy; the search waits and tries again a few times before giving up.
    """
    params = {
        "query": f"{gdelt_query(topic)} sourcelang:english",
        "mode": "artlist",
        "format": "json",
        "maxrecords": 75,
        "timespan": f"{days}d",
        "sort": "hybridrel",
    }
    body = _get_with_retry(f"{DOC_API}?{urllib.parse.urlencode(params)}")
    try:
        data = json.loads(body) if body.strip() else {}
    except ValueError as e:
        # GDELT answers errors (query too short, rate limit) in plain text.
        raise TopicError(f"GDELT article search: {body.strip()[:200]}") from e
    found: list[Found] = []
    titles: set[str] = set()
    for item in data.get("articles", []):
        # Wire stories run on dozens of sites under one headline; keep one copy.
        title = " ".join((item.get("title") or "").split())
        key = title.lower()
        if not item.get("url") or key in titles:
            continue
        titles.add(key)
        seen = item.get("seendate") or ""
        found.append(
            Found(
                url=item["url"],
                title=title,
                seen=datetime.strptime(seen[:8], "%Y%m%d").date() if len(seen) >= 8 else None,
                domain=item.get("domain") or "",
            )
        )
        if len(found) >= limit:
            break
    return found


def _fetch(found: Found) -> Article | None:
    try:
        article = fetch_article(found.url)
    except ArticleError as e:
        log.info("skipping %s: %s", found.url, e)
        return None
    article.title = article.title or found.title
    article.published = article.published or found.seen
    article.site = article.site or found.domain
    return article


def _claude_in_parallel(articles: list[Article], kind: str | None, today: date) -> list:
    """Claude extractions run side by side (they do not touch the database). Articles
    without one, or whose extraction fails, are extracted one by one afterwards."""
    extractor = get_extractor(kind)
    if extractor.name != "claude":
        return [None] * len(articles)

    def one(article: Article):
        try:
            return extractor.extract(None, article, article.published or today)
        except ExtractionError as e:
            log.warning("Claude could not read %s: %s", article.url, e)
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, articles))


ExtractFn = Callable[[Session, Article, date, str | None], tuple]


def build_topic_board(db: Session, body: TopicIn, found: list[Found], extract: ExtractFn) -> Board:
    with ThreadPoolExecutor(max_workers=6) as pool:
        articles = [a for a in pool.map(_fetch, found) if a is not None]
    if not articles:
        raise TopicError("None of the articles found could be read")
    today = date.today()
    board = Board(
        title=body.topic[:300],
        origin="topic",
        prompt=body.topic,
        anchor_date=max((a.published for a in articles if a.published), default=today),
        notes=f"Read {len(articles)} of {len(found)} articles found by GDELT's article search.",
    )
    db.add(board)
    db.flush()
    names = set()
    # Fewer events per article than a single-article board, so the merged board stays
    # readable; the shared cap still applies.
    settings = draft.RuleSettings(lookback_days=30, events_per_place=3, events_per_actor=3)
    unique, seen_urls = [], set()
    for article in articles:
        if (key := normalized_url(article.url)) not in seen_urls:
            seen_urls.add(key)
            unique.append(article)
    ready = _claude_in_parallel(unique, body.extractor, today)
    for i, article in enumerate(unique):
        anchor = article.published or today
        if ready[i] is not None:
            extraction, name, note = ready[i], "claude", ""
        else:
            extraction, name, note = extract(db, article, anchor, body.extractor)
        names.add(name)
        if note:
            board.notes += f"\n{note}"
        board.extractor = name
        draft.build_from_article(
            db, board, article, extraction, anchor, settings, article_key=f"article:{i}"
        )
    board.extractor = ", ".join(sorted(names))
    return board


def build_from_words(db: Session, body: TopicIn, extract: ExtractFn, problem: str) -> Board:
    """A topic board without articles: the places and actors the topic names, and the
    events around them. Used when the article search is down or finds nothing."""
    today = date.today()
    words = Article(text=body.topic, title=f"Topic: {body.topic}", published=today)
    extraction, name, note = extract(db, words, today, body.extractor)
    if not extraction.places and not extraction.actors:
        raise TopicError("Nothing in the events data matches the topic's words")
    board = Board(
        title=body.topic[:300],
        origin="topic",
        prompt=body.topic,
        anchor_date=today,
        extractor=name,
        notes=f"{problem}. Built from the topic's words and the events data instead."
        + (f"\n{note}" if note else ""),
    )
    db.add(board)
    db.flush()
    draft.build_from_article(
        db,
        board,
        words,
        extraction,
        today,
        draft.RuleSettings(lookback_days=body.days),
        article_key="topic",
    )
    return board
