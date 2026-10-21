import pytest
from sqlalchemy import text

from app.boards.extract import focus_from_counts
from app.boards.names import (
    actor_aliases,
    actor_key,
    actor_label,
    clean_source_url,
    detect_countries,
    expand_saint,
    find_alias,
    fold,
    gdelt_codes,
    looks_like_person,
    normalized_url,
    parse_state_actor,
    place_key,
    place_label,
    proper_phrases,
    quote_around,
)

PLACE_NAMES = [
    "Saraqib town",
    "Damascus city",
    "Gaza, Israel (general), Israel",
    "Mexico City",
    "Kyiv, Kyyiv, Misto, Ukraine",
    "Idlib governorate",
    "Bab al Hawa",
]
ACTOR_NAMES = [
    "Military Forces of Russia (2000-)",
    "Government of Ukraine (2019-)",
    "Hamas",
    "JNIM: Group for Support of Islam and Muslims",
    "Police Forces of Ukraine (2019-) State Border Guard Service",
]


@pytest.mark.parametrize("name", PLACE_NAMES)
def test_place_key_matches_sql(session, name):
    """The Python key and the indexed SQL key must agree, or lookups silently miss."""
    sql = session.scalar(text("SELECT board_place_key(:n)"), {"n": name})
    assert place_key(name) == sql


@pytest.mark.parametrize("name", ACTOR_NAMES)
def test_actor_key_matches_sql(session, name):
    sql = session.scalar(text("SELECT board_actor_key(:n)"), {"n": name})
    assert actor_key(name) == sql


def test_place_key_strips_ucdp_kind_but_not_proper_names():
    assert place_key("Saraqib town") == "saraqib"
    assert place_key("Gaza, Israel (general), Israel") == "gaza"
    assert place_key("Mexico City") == "mexico city"
    assert place_label("Kyiv city") == "Kyiv"


def test_state_actor_parsing():
    russia = parse_state_actor("Military Forces of Russia (2000-) Air Force")
    assert (russia.iso3, russia.branch, russia.unit) == ("RUS", "military", "air force")
    assert parse_state_actor("Government of South Sudan (2011-)").iso3 == "SSD"
    assert parse_state_actor("Hamas") is None


def test_actor_labels_group_state_forces():
    assert actor_label("Military Forces of Russia (2000-)") == "Russian state forces"
    assert actor_label("Government of Russia (Soviet Union)") == "Russian state forces"
    assert actor_label("Military Forces of Russia (2000-) Air Force") == "Russian Air Force"
    assert actor_label("Wagner Group") == "Wagner Group"


def test_actor_aliases_cover_article_phrasing():
    aliases = actor_aliases("Military Forces of Russia (2000-)")
    assert {"russian forces", "russian troops", "russian strikes", "russian state forces"} <= set(
        aliases
    )
    # A unit is matched by its own name only, not by "Russian forces".
    unit = actor_aliases("Military Forces of Russia (2000-) Air Force")
    assert "russian air force" in unit and "russian forces" not in unit
    # Generic and country-only names get no aliases, so they cannot match on their own.
    assert actor_aliases("POLICE") == []
    assert actor_aliases("RUSSIA") == []


def test_gdelt_codes_follow_iso3():
    assert gdelt_codes("Military Forces of Russia (2000-)") == ["RUS", "RUSMIL"]
    assert gdelt_codes("Police Forces of Ukraine (2019-)") == ["UKRCOP"]
    assert gdelt_codes("Hamas") == []


def test_detect_countries_counts_names_and_adjectives():
    counts = detect_countries(
        "Russian drones hit Ukraine. Ukrainian officials said Russia fired 40 missiles. "
        "South Sudan was not mentioned as Sudan."
    )
    assert counts["UKR"] == 2 and counts["RUS"] == 2
    # "Sudan" inside "South Sudan" is counted once, for South Sudan.
    assert counts["SSD"] == 1 and counts["SDN"] == 1


def test_focus_countries_keep_the_story_not_passing_mentions():
    assert focus_from_counts({"UKR": 23, "RUS": 20, "USA": 7, "PRT": 1}) == ["UKR", "RUS"]
    assert focus_from_counts({"ISR": 12, "SAU": 8, "YEM": 8, "PSE": 7, "GBR": 1}) == [
        "ISR",
        "SAU",
        "YEM",
        "PSE",
    ]
    assert focus_from_counts({}) == []


def test_proper_phrases_and_saint():
    phrases = proper_phrases("Shelling hit Deir al-Balah and St. Petersburg on Tuesday.")
    assert "Deir al-Balah" in phrases
    assert "Saint Petersburg" in phrases
    assert "Tuesday" not in phrases
    assert expand_saint("St Helena") == "Saint Helena"


def test_person_names_are_not_places():
    text_ = "President Volodymyr Zelenskyy spoke. Volodymyr Zelenskyy left Kherson Oblast."
    assert looks_like_person(text_, "Volodymyr")
    assert not looks_like_person(text_, "Kherson")
    assert not looks_like_person("Strikes hit Kherson, officials said.", "Kherson")


def test_quote_around_copies_the_article_text():
    body = "Officials spoke. Planes at St. Petersburg airport were delayed. More later."
    assert (
        quote_around(body, "Saint Petersburg") == "Planes at St. Petersburg airport were delayed."
    )
    assert quote_around(body, "Nowhere") is None


def test_find_alias_whole_words_only():
    folded = fold("Russian troops advanced near Bakhmut.")
    assert find_alias(folded, "russian troops") == 0
    assert find_alias(folded, "russian troop") == -1


def test_clean_source_url_drops_tracking_and_refuses_the_rest():
    assert (
        clean_source_url("https://news.example/a/b?utm_source=x&utm_medium=y")
        == "https://news.example/a/b"
    )
    assert clean_source_url("https://news.example/story#comments") == "https://news.example/story"
    # A query the page needs, or a non-https link, cannot go on a globe card.
    assert clean_source_url("https://news.example/view?id=123") is None
    assert clean_source_url("http://news.example/a") is None
    assert clean_source_url(None) is None
    assert normalized_url("https://www.News.example/a/") == "news.example/a"


def test_surnames_and_prefixed_places():
    text_ = "Sheikh Ahmed Yassin spoke. Ahmed Yassin left. Fighting in North Darfur and Darfur."
    assert looks_like_person(text_, "Yassin")
    assert not looks_like_person(text_, "Darfur")
    assert not looks_like_person("The ministry in Kyiv said.", "Kyiv")


def test_ethnic_and_religious_words_are_not_actors():
    assert actor_aliases("Arab") == []
    assert actor_aliases("Muslims") == []


def test_known_group_aliases():
    assert "houthis" in actor_aliases("Ansarallah")
    assert actor_label("Ansarallah") == "Houthis (Ansarallah)"
    assert {"islamic state", "isis", "daesh"} <= set(actor_aliases("IS"))
    assert actor_label("IS") == "Islamic State"


def test_long_quotes_are_cut_at_words():
    body = "Officials said. " + "word " * 60 + "the town of Taybeh was raided " + "more " * 60 + "."
    quote = quote_around(body, "Taybeh", width=80)
    assert quote.startswith("…") and quote.endswith("…")
    assert "Taybeh" in quote
    assert all(
        part in ("word", "more", "the", "town", "of", "Taybeh", "was", "raided", "…")
        for part in quote.replace("…", " … ").split()
    )


def test_ucdp_yemen_names_are_relabelled():
    # UCDP's "Government of Yemen (North Yemen)" is the Houthi-run government in recent
    # data; it must not read as Yemen's recognised government.
    assert actor_label("Government of Yemen (North Yemen)") == "Houthis (UCDP: Government of Yemen)"
    aliases = actor_aliases("Government of Yemen (North Yemen)")
    assert "houthi rebels" in aliases and "yemeni forces" not in aliases
    assert gdelt_codes("Government of Yemen (North Yemen)") == []
    assert "yemeni government forces" in actor_aliases(
        "Forces of the Presidential Leadership Council"
    )


def test_resolve_actor_does_not_confuse_neighbouring_armies():
    from app.boards.draft import resolve_actor
    from app.boards.gazetteer import Actor

    names = [
        "Military Forces of Russia (2000-)",
        "Military Forces of Belarus (1994-)",
        "Government of Yemen (North Yemen)",
    ]
    candidates = [Actor(name=n, events=1, aliases=actor_aliases(n)) for n in names]
    assert resolve_actor("Russian state forces", candidates) == [
        "Military Forces of Russia (2000-)"
    ]
    assert resolve_actor("Russian troops", candidates) == ["Military Forces of Russia (2000-)"]
    assert resolve_actor("Houthi rebel", candidates) == ["Government of Yemen (North Yemen)"]
    assert resolve_actor("Belarusian army", candidates) == ["Military Forces of Belarus (1994-)"]
