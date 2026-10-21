"""Text helpers for matching an article's words to the names in the events table.

Nothing here touches the database, so each rule can be tested on its own.
"""

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from app.countries import all_countries

# Keep in step with board_place_key() and board_actor_key() in migration 0006.
_PLACE_SUFFIX = re.compile(
    r"\s+(town|city|village|governorate|province|district|area|region|camp|county|"
    r"municipality|oblast|state|prefecture|subdistrict|neighbourhood|neighborhood)$"
)
_PARENTHESES = re.compile(r"\s*\([^)]*\)")


def place_key(name: str | None) -> str | None:
    if name is None:
        return None
    return _PLACE_SUFFIX.sub("", name.split(",", 1)[0]).strip().lower()


def place_label(name: str) -> str:
    """A place name without UCDP's lower-case kind: 'Kyiv city' -> 'Kyiv'."""
    return _PLACE_SUFFIX.sub("", name).strip() or name


def actor_key(name: str | None) -> str | None:
    if name is None:
        return None
    return _PARENTHESES.sub("", name).strip().lower()


def fold(text: str) -> str:
    """Lower case without accents, so 'Bouaké' and 'Bouake' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


# Adjectives news writers use for a country. Only countries that often appear in conflict
# reporting are listed; others are still found by name.
DEMONYMS: dict[str, list[str]] = {
    "AFG": ["Afghan"],
    "ARM": ["Armenian"],
    "AZE": ["Azerbaijani"],
    "BFA": ["Burkinabe", "Burkinabé"],
    "BLR": ["Belarusian"],
    "CAF": ["Central African"],
    "CHN": ["Chinese"],
    "COD": ["Congolese"],
    "COL": ["Colombian"],
    "EGY": ["Egyptian"],
    "ETH": ["Ethiopian"],
    "FRA": ["French"],
    "GBR": ["British"],
    "HTI": ["Haitian"],
    "IND": ["Indian"],
    "IRN": ["Iranian"],
    "IRQ": ["Iraqi"],
    "ISR": ["Israeli"],
    "JOR": ["Jordanian"],
    "KEN": ["Kenyan"],
    "LBN": ["Lebanese"],
    "LBY": ["Libyan"],
    "MLI": ["Malian"],
    "MMR": ["Myanmar", "Burmese"],
    "MOZ": ["Mozambican"],
    "MEX": ["Mexican"],
    "NER": ["Nigerien"],
    "NGA": ["Nigerian"],
    "PAK": ["Pakistani"],
    "PSE": ["Palestinian"],
    "PHL": ["Philippine", "Filipino"],
    "PRK": ["North Korean"],
    "RUS": ["Russian"],
    "SAU": ["Saudi"],
    "SDN": ["Sudanese"],
    "SOM": ["Somali"],
    "SSD": ["South Sudanese"],
    "SYR": ["Syrian"],
    "TCD": ["Chadian"],
    "TUR": ["Turkish"],
    "UKR": ["Ukrainian"],
    "USA": ["American", "US", "U.S."],
    "VEN": ["Venezuelan"],
    "YEM": ["Yemeni"],
}

# Other names for a country, beyond the crosswalk's own name.
COUNTRY_ALIASES: dict[str, list[str]] = {
    "USA": ["United States", "U.S.", "USA", "America"],
    "GBR": ["United Kingdom", "Britain", "UK", "U.K."],
    "RUS": ["Russia", "Russian Federation"],
    "IRN": ["Iran"],
    "SYR": ["Syria"],
    "COD": ["DR Congo", "DRC", "Democratic Republic of the Congo"],
    "PSE": ["Gaza Strip", "West Bank", "Palestine"],
    "KOR": ["South Korea"],
    "PRK": ["North Korea"],
    "MMR": ["Myanmar", "Burma"],
    "VEN": ["Venezuela"],
    "BOL": ["Bolivia"],
    "TZA": ["Tanzania"],
    "LAO": ["Laos"],
    "VNM": ["Vietnam"],
    "CIV": ["Ivory Coast", "Côte d'Ivoire"],
    "TUR": ["Turkey", "Türkiye"],
    "MDA": ["Moldova"],
    "SSD": ["South Sudan"],
    "CAF": ["Central African Republic"],
}


# Actor names in the event sources that say nothing about who acted. GDELT codes roles
# as actors ("POLICE", "PROTESTER"); matching them would link every story to thousands of
# unrelated events.
def _words(text: str) -> list[str]:
    return text.split()


GENERIC_ACTORS = frozenset(
    _words("""
    police military government authorities protester protesters civilian civilians
    president prime minister minister rebel rebels militant militants insurgent insurgents
    army armed forces security forces soldier soldiers troops citizen citizens resident
    residents student students worker workers media journalist journalists opposition
    court judge lawmaker parliament legislature party community village villagers gang
    criminal criminals attacker attackers gunmen gunman terrorist terrorists unidentified
    armed group unidentified armed group unknown israeli palestinian company business
    school hospital official officials leader leaders crowd mob children women men people
    arab arabs muslim muslims christian christians jewish tribal tribe tribes ethnic african
    european kurd kurds
    """)
) | {
    "unidentified armed group",
    "unidentified military forces",
    "rioters",
    "protesters",
    "civilians",
    "prime minister",
    "security forces",
    "armed forces",
}


@lru_cache
def country_names() -> dict[str, str]:
    """Every name and adjective that identifies a country, mapped to its ISO3 code."""
    names: dict[str, str] = {}
    for iso3, country in all_countries().items():
        names[country.name] = iso3
    for iso3, aliases in COUNTRY_ALIASES.items():
        for alias in aliases:
            names[alias] = iso3
    for iso3, adjectives in DEMONYMS.items():
        for adjective in adjectives:
            names[adjective] = iso3
    return names


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    # Word boundaries that also work next to dots ("U.S.") and hyphens.
    return re.compile(r"(?<![\w.-])" + re.escape(phrase) + r"(?![\w-])")


@lru_cache
def _country_patterns() -> list[tuple[str, re.Pattern[str]]]:
    # Longest names first, so "South Sudan" is counted before "Sudan".
    names = sorted(country_names().items(), key=lambda kv: -len(kv[0]))
    return [(iso3, _phrase_pattern(name)) for name, iso3 in names]


def detect_countries(text: str) -> dict[str, int]:
    """How often each country is named in the text, keyed by ISO3, most mentioned first."""
    counts: dict[str, int] = {}
    remaining = text
    for iso3, pattern in _country_patterns():
        hits = len(pattern.findall(remaining))
        if hits:
            counts[iso3] = counts.get(iso3, 0) + hits
            # Blank matched names so "Sudan" inside "South Sudan" is not counted twice.
            remaining = pattern.sub(" ", remaining)
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def country_words() -> frozenset[str]:
    return frozenset(name.lower() for name in country_names())


_WORD = r"[A-ZÀ-Ý][\w'’-]*"
_JOINER = r"(?:al|el|de|du|di|da|la|le|ash|as|ar|an|ad|bin|ibn|of|van|der)"
# A run of capitalised words, allowing Arabic and French joiners: "Deir al-Balah",
# "Bab al Hawa", "Kafr Nabl".
_PROPER_RUN = re.compile(rf"{_WORD}(?:[\s-]+(?:{_JOINER}[\s-]+)?{_WORD})*")

_NOT_PLACES = frozenset(
    _words("""
    the a an this that these those he she they it we i you his her their its our
    monday tuesday wednesday thursday friday saturday sunday january february march april
    may june july august september october november december reuters ap afp bbc cnn
    mr mrs ms dr president minister general colonel captain sergeant spokesman spokesperson
    north south east west northern southern eastern western central new old
    """)
)


_SAINT = re.compile(r"\bSt\.?\s+(?=[A-Z])")


def expand_saint(text: str) -> str:
    """'St. Petersburg' -> 'Saint Petersburg', the form the event sources use."""
    return _SAINT.sub("Saint ", text)


def _sentence_start(text: str, position: int) -> int:
    dot = position
    while (dot := text.rfind(".", 0, dot)) != -1:
        if not re.search(r"\bSt$", text[max(0, dot - 3) : dot]):
            return dot + 1
    return 0


def proper_phrases(text: str, max_words: int = 4) -> set[str]:
    """Candidate names: capitalised runs and every sub-run of up to `max_words` words."""
    found: set[str] = set()
    for match in _PROPER_RUN.finditer(expand_saint(text)):
        words = re.split(r"\s+", match.group(0).strip())
        for size in range(1, min(max_words, len(words)) + 1):
            for start in range(len(words) - size + 1):
                phrase = " ".join(words[start : start + size]).strip("'’-")
                if len(phrase) >= 3 and phrase.lower() not in _NOT_PLACES:
                    found.add(phrase)
    return found


def quote_around(text: str, phrase: str, width: int = 220) -> str | None:
    """The sentence (or a window of text) where `phrase` first appears, for evidence.

    The quote is copied from the text as written, so 'Saint Petersburg' is found as
    'St. Petersburg' when that is what the article says.
    """
    candidates = [phrase]
    if phrase.startswith("Saint "):
        candidates += [f"St. {phrase[6:]}", f"St {phrase[6:]}"]
    match = next(
        (m for c in candidates if (m := _phrase_pattern(c).search(text))), None
    ) or re.search(re.escape(phrase), text, re.IGNORECASE)
    if not match:
        return None
    # Sentence bounds, ignoring the dot in "St." so a quote does not start mid-name. A long
    # sentence is cut to a window around the name, at whole words, marked with an ellipsis.
    sentence_start = _sentence_start(text, match.start())
    start = max(sentence_start, match.start() - width // 2, 0)
    if start > sentence_start:
        start = text.find(" ", start, match.start()) + 1 or start
    end_dot = text.find(".", match.end())
    sentence_end = end_dot + 1 if end_dot != -1 else len(text)
    end = min(sentence_end, match.end() + width // 2)
    if end < sentence_end:
        end = text.rfind(" ", match.end(), end) if text.rfind(" ", match.end(), end) > 0 else end
    snippet = " ".join(text[start:end].split())
    if not snippet:
        return None
    return ("…" if start > sentence_start else "") + snippet + ("…" if end < sentence_end else "")


# Armed groups news writers call by another name than the event sources do. Keys are the
# sources' names as actor_key() gives them (UCDP calls the Houthis "Ansarallah" and the
# Islamic State "IS"); values are what articles say.
KNOWN_ALIASES: dict[str, list[str]] = {
    "ansarallah": ["houthi", "houthis", "houthi rebels", "houthi movement", "ansar allah"],
    "is": ["islamic state", "islamic state group", "isis", "isil", "daesh"],
    "rsf": ["rapid support forces", "rapid support force"],
    "taleban": ["taliban"],
    "ttp": ["pakistani taliban", "tehreek-e-taliban pakistan", "tehrik-i-taliban pakistan"],
    "aqap": ["al-qaeda in the arabian peninsula", "al qaeda in the arabian peninsula"],
    "al-qaida": ["al-qaeda", "al qaeda"],
    "al-shabaab": ["al shabaab", "al-shabab", "shabab"],
    "hezbollah": ["hizbollah", "hizballah"],
    "pij": ["palestinian islamic jihad", "islamic jihad"],
    "jnim": ["jama'at nusrat al-islam wal-muslimin", "group for support of islam and muslims"],
    "sdf": ["syrian democratic forces"],
    "pkk": ["kurdistan workers' party", "kurdistan workers party"],
    "m23": ["march 23 movement"],
    "wagner": ["wagner group"],
}
KNOWN_LABELS = {
    "ansarallah": "Houthis (Ansarallah)",
    "is": "Islamic State",
    "rsf": "Rapid Support Forces",
    "taleban": "Taliban",
    "ttp": "Pakistani Taliban (TTP)",
    "pij": "Palestinian Islamic Jihad",
}

# Source names that do not mean what their words say. UCDP codes the Houthi-run government
# in Sanaa as "Government of Yemen (North Yemen)": its 2024-25 events include the US, UK
# and Israeli strikes on the Houthis. The internationally recognised government appears
# as "Forces of the Presidential Leadership Council". Before 2015 the same "Government of
# Yemen" name was the government fighting Ansarallah, so these labels are for recent data.
SPECIAL_ACTORS: dict[str, dict[str, list[str] | str]] = {
    "government of yemen": {
        "label": "Houthis (UCDP: Government of Yemen)",
        "aliases": ["houthi", "houthis", "houthi rebels", "houthi movement", "ansar allah",
                    "ansarallah", "houthi-run government", "houthi authorities"],
    },
    "forces of the presidential leadership council": {
        "label": "Yemen's recognised government (Presidential Leadership Council)",
        "aliases": ["presidential leadership council", "yemeni government",
                    "yemeni government forces", "yemen's government"],
    },
}  # fmt: skip

# How UCDP and ACLED name a state's forces. UCDP's "Government of X" is the state as a
# side in a war, so it stands for the same forces as ACLED's "Military Forces of X".
_STATE_PREFIXES = {
    "military forces of ": "military",
    "government of ": "military",
    "police forces of ": "police",
}
# What articles call those forces, and their attacks: "Russian troops", "Russian strikes".
_STATE_FORMS = {
    "military": [
        "{c} forces", "{c} military", "{d} forces", "{d} military", "{d} army",
        "{d} troops", "{d} soldiers", "{d} attacks", "{d} attack", "{d} strikes",
        "{d} strike", "{d} drones", "{d} drone", "{d} missiles", "{d} missile",
        "{d} shelling", "{d} airstrikes", "{d} government", "{d} authorities",
    ],
    "police": ["{c} police", "{d} police"],
}  # fmt: skip


@dataclass(frozen=True)
class StateActor:
    iso3: str
    country: str
    branch: str
    # A named part of the forces after the country: "Air Force", "National Guard".
    unit: str | None


def parse_state_actor(name: str) -> StateActor | None:
    """'Military Forces of Russia (2000-) Air Force' -> Russia, military, 'air force'."""
    key = actor_key(name) or ""
    if key in SPECIAL_ACTORS:
        return None
    names = {k.lower(): v for k, v in country_names().items()}
    for prefix, branch in _STATE_PREFIXES.items():
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix) :]
        # The longest country name the rest starts with, so "south sudan" beats "sudan".
        for country in sorted((c for c in names if rest.startswith(c)), key=len, reverse=True):
            unit = rest[len(country) :].strip() or None
            if unit is None or rest[len(country)] == " ":
                return StateActor(names[country], country, branch, unit)
    return None


def actor_label(name: str) -> str:
    """A readable name for an event-source actor: 'Russian state forces', 'Wagner Group'."""
    key = actor_key(name) or ""
    if key in SPECIAL_ACTORS:
        return str(SPECIAL_ACTORS[key]["label"])
    state = parse_state_actor(name)
    if state is None:
        return KNOWN_LABELS.get(key, _PARENTHESES.sub("", name).strip())
    demonym = (DEMONYMS.get(state.iso3) or [state.country.title()])[0]
    if state.unit:
        return f"{demonym} {state.unit.title()}"
    return f"{demonym} {'police' if state.branch == 'police' else 'state forces'}"


def gdelt_codes(name: str) -> list[str]:
    """GDELT's CAMEO codes for a state actor: Russia's forces are coded RUS or RUSMIL.

    CAMEO uses ISO3 country codes, so they follow from the actor's country. Non-state
    actors have no fixed code and match GDELT by name instead.
    """
    state = parse_state_actor(name)
    if state is None:
        return []
    if state.branch == "police":
        return [f"{state.iso3}COP"]
    return [state.iso3, f"{state.iso3}MIL"]


def actor_aliases(name: str) -> list[str]:
    """Phrases an article might use for an actor named as the event sources name it.

    "Military Forces of Russia (2000-)" -> "russian forces", "russian strikes", ...
    Short or generic names get no aliases, so they cannot match on their own.
    """
    key = actor_key(name) or ""
    if not key or key in GENERIC_ACTORS or key in country_words():
        return []
    aliases = {key, actor_label(name).lower(), *KNOWN_ALIASES.get(key, [])}
    aliases.update(SPECIAL_ACTORS.get(key, {}).get("aliases", []))
    state = parse_state_actor(name)
    if state is not None:
        demonyms = [d.lower() for d in DEMONYMS.get(state.iso3, [])]
        if state.unit:
            # Units are matched by their own name only: "Russian Air Force", "Russian Navy".
            aliases.update(f"{d} {state.unit}" for d in demonyms)
            aliases.add(f"{state.country} {state.unit}")
            if len(state.unit.split()) >= 3:
                aliases.add(state.unit)
        else:
            for form in _STATE_FORMS[state.branch]:
                if "{d}" in form:
                    aliases.update(form.format(d=d) for d in demonyms)
                else:
                    aliases.add(form.format(c=state.country))
    # An actor such as "Hamas" or "Rapid Support Forces" is matched by its own name; an
    # acronym in the name ("RSF") is matched too when the source gives one.
    for acronym in re.findall(r"\b([A-Z]{3,6})\b", name):
        if acronym.lower() not in GENERIC_ACTORS:
            aliases.add(acronym.lower())
    return sorted(a for a in aliases if len(a) >= 3)


# Words that may follow a place name without making it part of a person's name.
_PLACE_WORDS = frozenset(
    _words("""
    oblast region province governorate district city county state airport base port
    strip valley river bay island islands mountains hills camp crossing border front
    """)
)


# Words that may come before a place name: "North Darfur", "Greater Khartoum".
_PLACE_PREFIXES = frozenset(
    _words("""
    north south east west northern southern eastern western central upper lower greater
    new old saint al el the in at near from to of and
    """)
)


def looks_like_person(text: str, phrase: str) -> bool:
    """True when a one-word name always stands next to another name, as in a person's.

    'Volodymyr' in 'Volodymyr Zelenskyy' is a town in the gazetteer and a first name here;
    'Yassin' in 'Ahmed Yassin' is a surname. 'Kherson Oblast' keeps Kherson, since Oblast
    is a place word, and 'North Darfur' keeps Darfur.
    """
    if " " in phrase:
        return False
    word = re.escape(phrase)
    hits = list(re.finditer(rf"(?<![\w-]){word}(?![\w-])", text))
    if not hits:
        return False

    def beside_a_name(m: re.Match) -> bool:
        after = re.match(r"(?:'s)?\s+([A-Z][\w'-]*)", text[m.end() :])
        before = re.search(r"([A-Z][\w'-]*)\s+$", text[: m.start()])
        return bool(
            (after and after.group(1).lower() not in _PLACE_WORDS)
            or (before and before.group(1).lower() not in _PLACE_PREFIXES)
        )

    return all(beside_a_name(m) for m in hits)


def find_alias(text_folded: str, alias: str) -> int:
    """Where an alias first appears in folded text, or -1. Whole words only."""
    match = re.search(r"(?<![\w-])" + re.escape(fold(alias)) + r"(?![\w-])", text_folded)
    return match.start() if match else -1


def clean_source_url(url: str | None) -> str | None:
    """An https link the globe's source cards accept: no credentials, query or fragment.

    gods-eye-view refuses card links with a query string, so tracking parameters are
    dropped. A link that needs its query to work, or is not https, is returned as None
    and the card shows the source name instead.
    """
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    if parts.query and not all(
        k.split("=")[0].lower().startswith(("utm_", "fbclid", "gclid", "ref", "cmp", "ocid"))
        for k in parts.query.split("&")
    ):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


def normalized_url(url: str | None) -> str | None:
    """A URL reduced to host and path, to compare the same article's links."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if not parts.hostname:
        return None
    host = parts.hostname.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"
