"""Fetch a news article and reduce it to its title, date and paragraphs."""

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

MAX_BYTES = 3 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; GlobalConflictMap/0.1; +https://github.com/)"


class ArticleError(Exception):
    """The article could not be fetched or had no readable text."""


@dataclass
class Article:
    text: str
    title: str | None = None
    url: str | None = None
    site: str | None = None
    published: date | None = None


def check_public_url(url: str) -> None:
    """Refuse URLs that would make the API fetch from this machine or its network."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ArticleError("Only http and https article links can be fetched")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ArticleError(f"Could not resolve {parts.hostname}") from e
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ArticleError("Article links must point to a public website")


class _NoRedirectToPrivate(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_article(url: str, timeout: float = 20.0) -> Article:
    check_public_url(url)
    opener = urllib.request.build_opener(_NoRedirectToPrivate)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
            final_url = response.geturl()
    except urllib.error.HTTPError as e:
        raise ArticleError(f"The site answered {e.code}; paste the article text instead") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ArticleError(f"Could not fetch the article: {e}") from e
    if len(raw) > MAX_BYTES:
        raise ArticleError("The page is larger than 3 MB")
    article = parse_html(raw.decode(charset, errors="replace"))
    article.url = final_url or url
    if len(article.text) < 200:
        raise ArticleError(
            "Found too little article text (the site may need a login or JavaScript); "
            "paste the article text instead"
        )
    return article


class _ArticleParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.paragraphs: list[str] = []
        self.json_ld: list[str] = []
        self._skip = 0
        self._in_title = False
        self._paragraph: list[str] | None = None
        self._in_json_ld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            name = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if name and a.get("content"):
                self.meta.setdefault(name, a["content"])
        elif tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_json_ld = True
            self.json_ld.append("")
        elif tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "p" and not self._skip:
            self._paragraph = []

    def handle_endtag(self, tag):
        if tag == "script" and self._in_json_ld:
            self._in_json_ld = False
        elif tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "p" and self._paragraph is not None:
            paragraph = " ".join("".join(self._paragraph).split())
            if len(paragraph) > 40:
                self.paragraphs.append(paragraph)
            self._paragraph = None

    def handle_data(self, data):
        if self._in_json_ld:
            self.json_ld[-1] += data
        elif self._in_title:
            self.title += data
        elif self._paragraph is not None and not self._skip:
            self._paragraph.append(data)


def parse_html(html: str) -> Article:
    parser = _ArticleParser()
    parser.feed(html)
    meta = parser.meta
    title = meta.get("og:title") or meta.get("twitter:title") or parser.title.strip() or None
    published = None
    for name in (
        "article:published_time",
        "og:published_time",
        "datepublished",
        "date",
        "pubdate",
        "dc.date",
    ):
        if published := parse_date(meta.get(name)):
            break
    if published is None:
        for block in parser.json_ld:
            match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', block)
            if match and (published := parse_date(match.group(1))):
                break
    if title is None:
        for block in parser.json_ld:
            try:
                headline = json.loads(block).get("headline")
            except (ValueError, AttributeError):
                continue
            if isinstance(headline, str):
                title = headline
                break
    return Article(
        text="\n\n".join(parser.paragraphs),
        title=" ".join(title.split()) if title else None,
        site=meta.get("og:site_name"),
        published=published,
    )


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    return None
