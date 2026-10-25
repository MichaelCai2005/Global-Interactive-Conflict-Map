"""Which of GDELT's violent events to keep off the map, and why.

GDELT's coder reads verbs, not stories. An article about a forest, a zoo's new penguins or
a debate becomes "use conventional military force" (CAMEO 190) when a sentence in it reads
that way, and ordinary crime (a club shooting, a murder trial) is coded with the same 18-20
root codes as war. On two days of the 15-minute feed (2026-10-17 and 10-23), about a third
of violent events came from articles that were not about violence at all, a third were
crime, and only a quarter were armed conflict or political violence.

screen() names the reason an event is not armed conflict, or returns None to keep it. It
uses only what GDELT itself gives: the article's headline, read from its URL, the article's
tone, and the actor codes. Every rule keeps an event when unsure, so a URL with no readable
headline (an id, or a site's front page) is never screened. Against 280 hand-labelled
articles from those two days, the rules kept all 47 that reported armed conflict and
screened out four in five non-violent articles and three in four crime stories (two in
three on 10-17, the day not used to write the rules). Crime left in is mostly shootings
whose headline names no arrest or court: "man critical after shooting in north Memphis".

Screened events stay in the database, because the risk model's GDELT features were fitted
on every event; the event endpoints hide them.
"""

import re
from collections.abc import Iterable
from urllib.parse import unquote, urlsplit

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

DATELINE = "dateline"
NOT_VIOLENCE = "not_violence"
CRIME = "crime"

# GDELT places a story where it is datelined, and US news is datelined Washington: a
# debate, a court ruling or a strike abroad becomes "fighting" at the White House.
DATELINE_ADM1 = "USDC"

# AvgTone counts positive minus negative words per hundred. Reports of violence score well
# below zero; no armed-conflict article in the labelled sample scored above -1.5.
TONE_CEILING = -1.0

# Fewer words than this is a section name or an id, not a headline.
MIN_HEADLINE_WORDS = 3

# Words that a report of violence uses. Prefixes match the start of a word, so "kill"
# matches "killed" and "killings"; short or ambiguous words ("war", not "warn") match whole.
VIOLENCE_PREFIXES = (
    "abduct", "abuse", "ambush", "ammunition", "arson", "artiller", "assail", "assassin",
    "assault", "atrocit", "attack", "bandit", "battl", "behead", "besieg", "blast",
    "bloodshed", "bloody", "bomb", "brawl", "brutal", "cartel", "casualt", "ceasefire",
    "clash", "combat", "conflict", "coup", "crackdown", "crossfire", "death", "destroy",
    "destruct", "drone", "escalat", "explod", "explos", "extremis", "fatal", "fight",
    "firefight", "gang", "genocide", "grenade", "gun", "hostage", "hostilit", "injur",
    "insurg", "insurrection", "invade", "invasion", "jihad", "kidnap", "kill", "knife",
    "lethal", "loot", "lynch", "machete", "martyr", "massacre", "militant", "militar",
    "militia", "missile", "mortar", "murder", "mutiny", "neutrali", "occupation",
    "occupied", "offensive", "paramilit", "police", "protest", "rape", "rebel", "retaliat",
    "riot", "rocket", "sabotage", "shell", "shoot", "shot", "siege", "skirmish", "slaughter",
    "sniper", "soldier", "stab", "strike", "teargas", "terror", "thug", "tortur", "troop",
    "unrest", "uprising", "victim", "violen", "weapon", "wound",
    "hamas", "hezbollah", "houthi", "shabaab", "taliban",
)  # fmt: skip
VIOLENCE_WORDS = {
    "armed", "arms", "army", "armies", "dead", "deadly", "deadliest", "die", "died", "dies",
    "dying", "execution", "executed", "fire", "fired", "firing", "forces", "frontline",
    "homicide", "idf", "ied", "isis", "mob", "navy", "naval", "raid", "raids", "raided", "rsf",
    "slain", "war", "wars", "warfare", "warplane", "warplanes", "warship", "warships",
}  # fmt: skip

# Words of policing and the courts: a story about an arrest, a trial or a sentence.
CRIME_PREFIXES = (
    "acquit", "arraign", "arrest", "attorney", "burglar", "carjack", "convict", "court",
    "custody", "detective", "domestic", "drug", "extradit", "fraud", "fugitive", "guilty",
    "homicide", "indict", "inmate", "investigat", "jail", "judge", "juror", "jury",
    "killer", "lawsuit", "lawyer", "manhunt", "manslaughter", "molest", "murder",
    "narcotic", "officer", "plead", "police", "prison", "prosecut", "rape", "rapist",
    "robber", "seiz", "sentenc", "sexual", "sheriff", "shooter", "steal", "stolen", "theft",
    "thie", "trial", "verdict",
)  # fmt: skip
CRIME_WORDS = {
    "allegedly", "bail", "charge", "charged", "charges", "cop", "cops", "deputies", "sue",
    "sued", "suspect", "suspects",
}  # fmt: skip

# Words of war, which outweigh the words of crime: "soldier jailed for war crimes" is still
# about a war, and so are police "clashes" with protesters.
CONFLICT_PREFIXES = (
    "airstrike", "artiller", "bandit", "battl", "cartel", "ceasefire", "clash", "combat",
    "coup", "crackdown", "drone", "extremis", "frontline", "genocide", "guerr", "insurg",
    "insurrection", "invade", "invasion", "jihad", "junta", "massacre", "militant",
    "militar", "militia", "missile", "mutiny", "occupation", "occupied", "offensive",
    "paramilit", "protest", "rebel", "riot", "rocket", "separatis", "shelling", "soldier",
    "teargas", "terror", "troop", "unrest", "uprising", "warplane", "warship",
    "hamas", "hezbollah", "houthi", "shabaab", "taliban",
)  # fmt: skip
CONFLICT_WORDS = {"army", "armies", "forces", "idf", "isis", "navy", "naval", "rsf", "war", "wars"}

# Accidents a coder reads as violence: "crews battle fire", "crash kills two".
ACCIDENT_PREFIXES = (
    "accident", "avalanche", "blaze", "collaps", "collide", "collision", "crash", "derail",
    "drown", "earthquake", "flood", "hurricane", "overdose", "stampede", "wildfire", "wreck",
)  # fmt: skip
ACCIDENT_WORDS = {"fire", "fires", "firefighter", "firefighters"}
# Words that make a fire or a crash deliberate: "gunmen open fire", "rioters set fires".
ATTACK_PREFIXES = (
    "airstrike", "arson", "attack", "bomb", "clash", "drone", "grenade", "gun", "loot",
    "militant", "missile", "protest", "raid", "rebel", "riot", "rocket", "shell", "shoot",
    "shot", "soldier", "stab", "terror", "troop",
)  # fmt: skip

# CAMEO actor type codes for armed groups and armed forces. An actor code is three-letter
# parts: country, then types, e.g. "PSEREB" is Palestinian rebels, "UAF" unidentified
# gunmen.
ARMED_ACTOR_TYPES = {"MIL", "REB", "INS", "SEP", "UAF", "RAD"}


def screen(
    url: str | None, tone: float | None, admin1: str | None, actor_codes: Iterable[str | None]
) -> str | None:
    """Why a violent GDELT event is not armed conflict, or None to keep it."""
    if admin1 == DATELINE_ADM1:
        return DATELINE
    if tone is not None and tone > TONE_CEILING:
        return NOT_VIOLENCE
    words = headline_words(url) if url else []
    if len(words) < MIN_HEADLINE_WORDS:
        return None
    if not _has(words, VIOLENCE_PREFIXES, VIOLENCE_WORDS):
        return NOT_VIOLENCE
    if _has(words, ACCIDENT_PREFIXES, ACCIDENT_WORDS) and not _has(
        words, ATTACK_PREFIXES, CONFLICT_WORDS
    ):
        return NOT_VIOLENCE
    armed = any(
        code[i : i + 3] in ARMED_ACTOR_TYPES
        for code in actor_codes
        if code
        for i in range(0, len(code), 3)
    )
    if (
        _has(words, CRIME_PREFIXES, CRIME_WORDS)
        and not armed
        and not _has(words, CONFLICT_PREFIXES, CONFLICT_WORDS)
    ):
        return CRIME
    return None


def headline_words(url: str) -> list[str]:
    """The headline a news URL carries in its path, as lowercase words.

    "https://a.example/2026/10/23/gunmen-open-fire-at-a-church.html" gives
    ["gunmen", "open", "fire", "at", "a", "church"]; a URL with no slug gives [].
    """
    try:
        path = unquote(urlsplit(url).path)
    except ValueError:
        return []
    # Some sites put the article id before the slug: "26667668.musk-speaks-starlink".
    parts = [re.sub(r"^\d+\.|\.(html?|php|aspx?|cms|ece)$", "", p) for p in path.split("/")]
    slugs = [p for p in parts if re.search(r"[a-z]{3,}[-_][a-z]{2,}", p, re.IGNORECASE)]
    if not slugs:
        return []
    words = re.split(r"[^a-z0-9]+", max(slugs, key=len).lower())
    # Drop numbers and ids such as "a1825477" or "article74111368".
    return [w for w in words if w and not w.isdigit() and not re.search(r"\d{4,}", w)]


def _has(words: list[str], prefixes: tuple[str, ...], whole: set[str]) -> bool:
    return any(w in whole or w.startswith(prefixes) for w in words)


def rescreen(db: Session | Connection) -> dict[str | None, int]:
    """Screens every stored violent GDELT event again, after the rules change; returns how
    many events each reason (None: kept) now covers. The caller commits.

    Migration 0011 runs this to fill the column in, so it takes a plain connection too."""
    rows = db.execute(
        text(
            "SELECT id, source_url, tone, admin1, attributes->>'actor1_code',"
            " attributes->>'actor2_code', screened_out FROM events"
            " WHERE source = 'gdelt' AND is_violent"
        )
    ).all()
    counts: dict[str | None, int] = {}
    changes = []
    for event_id, url, tone, admin1, actor1, actor2, before in rows:
        reason = screen(url, tone, admin1, (actor1, actor2))
        counts[reason] = counts.get(reason, 0) + 1
        if reason != before:
            changes.append({"id": event_id, "reason": reason})
    if changes:
        db.execute(text("CREATE TEMP TABLE gdelt_screen (id bigint, reason text)"))
        db.execute(text("INSERT INTO gdelt_screen VALUES (:id, :reason)"), changes)
        db.execute(
            text(
                "UPDATE events SET screened_out = s.reason FROM gdelt_screen s"
                " WHERE events.id = s.id"
            )
        )
        db.execute(text("DROP TABLE gdelt_screen"))
    return counts
