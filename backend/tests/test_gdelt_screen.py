import io

import pytest

from app.ingest import gdelt
from app.ingest.gdelt_screen import CRIME, DATELINE, NOT_VIOLENCE, headline_words, rescreen, screen
from app.ingest.loader import ingest_file
from tests.builders import gdelt_row, gdelt_tsv
from tests.test_ingest import write

# Mostly headlines GDELT coded as violence (CAMEO 18-20) in October 2026.
FOREST = "https://www.mynbc5.com/article/sakolsky-forest-retired-teacher-to-china-forest/74111368"


@pytest.mark.parametrize(
    ("url", "tone", "codes", "expected"),
    [
        # Coded 190, "use conventional military force", in Sichuan: the article is about a
        # Vermont forest.
        (FOREST, 1.2, ("CHN", None), NOT_VIOLENCE),
        # Not about violence, though the tone is negative.
        (
            "https://www.ft.example/asml-china-percent-sales-us-duv-restrictions-homegrown-equipment",
            -3.1,
            ("CHN", "USA"),
            NOT_VIOLENCE,
        ),
        (
            "https://www.dailybulletin.com/2026/10/20/la-zoo-welcomes-its-first-magellanic-penguins",
            -2.6,
            ("USA", None),
            NOT_VIOLENCE,
        ),
        # An accident, not an attack.
        (
            "https://www.wcvb.com/article/crews-battle-fire-at-multifamily-home-in-malden/74231652",
            -7.3,
            ("USA", None),
            NOT_VIOLENCE,
        ),
        # Crime: arrests, trials and sentences.
        (
            "https://newsradio710.iheart.com/content/2026-10-14-diddy-hospitalized-after-prison-fight/",
            -6.8,
            ("USA", "USA"),
            CRIME,
        ),
        (
            "https://fox17.com/news/local/second-man-arrested-in-east-tennessee-murder-investigation",
            -12.3,
            ("USA", None),
            CRIME,
        ),
        # Armed conflict and political violence, kept.
        (
            "https://www.thehindu.com/news/international/gunmen-open-fire-inside-a-church-in-jordan/article71616413.ece",
            -10.2,
            ("UAF", "GRC"),
            None,
        ),
        (
            "https://www.thecourier.com.au/story/9370371/rioters-loot-stores-set-fires-in-milan-during-protest/",
            -6.0,
            (None, None),
            None,
        ),
        (
            "https://www.arabnews.com/world/romania-shoots-down-two-drones-over-the-black-sea-3006873",
            -4.6,
            ("ROU", None),
            None,
        ),
        # Words of war outweigh words of crime, and so do armed actors.
        (
            "https://news.example/soldier-jailed-for-war-crimes-in-testland",
            -5.0,
            (None, None),
            None,
        ),
        ("https://news.example/court-hears-testville-attack-case", -5.0, ("TSTREB", None), None),
        # No headline to read: kept, whatever the article is.
        ("https://www.kyivpost.com/post/87476", -4.9, ("RUS", "UKR"), None),
        ("https://sana.sy/en/middle-east/2353079/", -12.7, ("ISR", "CVL"), None),
    ],
)
def test_screen(url, tone, codes, expected):
    assert screen(url, tone, None, codes) == expected


def test_screen_hides_washington_datelines_whatever_the_story():
    assert screen("https://sana.sy/en/2353079/", -9.0, "USDC", ("USA", None)) == DATELINE


def test_screen_keeps_events_without_tone_or_url():
    assert screen(None, None, None, (None, None)) is None


def test_headline_words():
    assert headline_words("https://news.example/2026/10/23/gunmen-open-fire.html") == [
        "gunmen",
        "open",
        "fire",
    ]
    # The slug after an article id, with numbers and ids dropped.
    assert headline_words("https://news.example/news/26667668.two-killed-in-3-blasts/") == [
        "two",
        "killed",
        "in",
        "blasts",
    ]
    assert headline_words("https://www.prokerala.com/news/articles/a1827998.html") == []


def test_parser_screens_violence_only():
    fight, protest = gdelt.parse(
        io.StringIO(
            gdelt_tsv(
                [
                    gdelt_row(GLOBALEVENTID="1", SOURCEURL=FOREST, AvgTone="1.2"),
                    gdelt_row(
                        GLOBALEVENTID="2",
                        EventRootCode="14",
                        EventCode="141",
                        SOURCEURL=FOREST,
                        AvgTone="1.2",
                    ),
                ]
            )
        )
    )
    assert fight.event.screened_out == NOT_VIOLENCE
    assert protest.event.screened_out is None


def test_screened_events_stay_stored_but_leave_the_map(client, session, tmp_path):
    rows = [
        gdelt_row(GLOBALEVENTID="1", SOURCEURL=FOREST, AvgTone="1.2"),
        gdelt_row(
            GLOBALEVENTID="2",
            ActionGeo_Lat="10",
            ActionGeo_Long="10",
            SOURCEURL="https://news.example/rebels-attack-army-post-near-testville",
        ),
    ]
    ingest_file(session, "gdelt", write(tmp_path, "20220301.export.CSV", gdelt_tsv(rows)))

    items = client.get("/events").json()["items"]
    assert [e["source_url"] for e in items] == [rows[1][-1]]
    assert client.get("/summary").json()["violent_events"] == 1
    # Both are stored, and screening them again changes nothing.
    assert rescreen(session) == {NOT_VIOLENCE: 1, None: 1}
