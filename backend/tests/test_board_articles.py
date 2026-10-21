from datetime import date

import pytest

from app.boards.articles import ArticleError, check_public_url, parse_date, parse_html

PAGE = """<!doctype html><html><head>
<title>Fallback title | Site</title>
<meta property="og:title" content="Strikes hit Testville">
<meta property="og:site_name" content="Test News">
<meta property="article:published_time" content="2026-10-16T08:30:00Z">
<script>var ignored = "<p>not text</p>";</script>
</head><body>
<nav><p>Home | World | Sport | Subscribe to our newsletter today</p></nav>
<article>
<p>KYIV, Ukraine (AP) — Russian strikes hit nine regions overnight, officials said on Friday.</p>
<p>Short.</p>
<p>The attacks damaged homes in Testville and wounded at least 15 people, the governor said.</p>
</article>
<footer><p>Copyright Test News, all rights reserved, do not republish this.</p></footer>
</body></html>"""


def test_parse_html_reads_title_date_and_paragraphs():
    article = parse_html(PAGE)
    assert article.title == "Strikes hit Testville"
    assert article.site == "Test News"
    assert article.published == date(2026, 10, 16)
    assert article.text.startswith("KYIV, Ukraine (AP)")
    assert "Testville" in article.text
    # Navigation, footers, scripts and fragments are not article text.
    assert "Subscribe" not in article.text
    assert "Copyright" not in article.text
    assert "Short." not in article.text


def test_parse_html_falls_back_to_json_ld():
    page = """<html><head><script type="application/ld+json">
    {"@type": "NewsArticle", "headline": "Clashes in Testville",
     "datePublished": "2026-10-12T10:00:00+02:00"}</script></head>
    <body><p>Fighting continued in Testville for a third day, residents said by phone.</p>
    </body></html>"""
    article = parse_html(page)
    assert article.title == "Clashes in Testville"
    assert article.published == date(2026, 10, 12)


def test_parse_date_forms():
    assert parse_date("2026-10-16") == date(2026, 10, 16)
    assert parse_date("2026-10-16T23:59:00Z") == date(2026, 10, 16)
    assert parse_date("Friday") is None
    assert parse_date(None) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/boards",
        "http://127.0.0.1/admin",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "file:///etc/passwd",
        "ftp://example.com/a",
    ],
)
def test_check_public_url_refuses_local_and_odd_urls(url):
    with pytest.raises(ArticleError):
        check_public_url(url)
