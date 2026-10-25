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
articles from those two days (app/data/gdelt_headline_labels.csv), the rules keep 46 of
the 47 that report armed conflict and screen out 83 of 102 non-violent articles and 60 of
77 crime stories. Crime left in is mostly shootings whose headline names no arrest or
court: "man critical after shooting in north Memphis".

screen_by_model() then reads the headlines the rules kept with a small classifier
(app.headline_model) and screens out those unlike news of armed conflict, unless the
headline names war outright. On the same sample, rules and model together keep 45 of the 47
conflict articles and show 22 crime or non-violent ones where the rules alone show 36.

Screened events stay in the database, because the risk model's GDELT features were fitted
on every event; the event endpoints hide them.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Protocol
from urllib.parse import unquote, urlsplit

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

DATELINE = "dateline"
NOT_VIOLENCE = "not_violence"
CRIME = "crime"
# The headline model finds the story unlike news of armed conflict.
NOT_CONFLICT = "not_conflict"

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
    "paramilit", "protest", "rebel", "riot", "rocket", "separatis", "settler", "shelling",
    "soldier", "teargas", "terror", "troop", "unrest", "uprising", "warplane", "warship",
    "hamas", "hezbollah", "houthi", "shabaab", "taliban",
)  # fmt: skip
CONFLICT_WORDS = {"army", "armies", "forces", "idf", "isis", "navy", "naval", "rsf", "war", "wars"}
# Words of war the headline model may not overrule. A protest alone is no sign of war.
WAR_PREFIXES = tuple(p for p in CONFLICT_PREFIXES if p != "protest")

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
    headline = headline_words(url) if url else []
    if len(headline) < MIN_HEADLINE_WORDS:
        return None
    if not _has(headline, VIOLENCE_PREFIXES, VIOLENCE_WORDS):
        return NOT_VIOLENCE
    if _has(headline, ACCIDENT_PREFIXES, ACCIDENT_WORDS) and not _has(
        headline, ATTACK_PREFIXES, CONFLICT_WORDS
    ):
        return NOT_VIOLENCE
    armed = any(
        code[i : i + 3] in ARMED_ACTOR_TYPES
        for code in actor_codes
        if code
        for i in range(0, len(code), 3)
    )
    if (
        _has(headline, CRIME_PREFIXES, CRIME_WORDS)
        and not armed
        and not _has(headline, CONFLICT_PREFIXES, CONFLICT_WORDS)
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
    return words(max(slugs, key=len)) if slugs else []


def words(text_: str) -> list[str]:
    """Lowercase words without numbers or ids such as "a1825477" or "article74111368"."""
    split = re.split(r"[^a-z0-9]+", text_.lower())
    return [w for w in split if w and not w.isdigit() and not re.search(r"\d{4,}", w)]


class ConflictModel(Protocol):
    threshold: float

    def conflict_probabilities(self, headlines: Sequence[str]) -> list[float]: ...


def screen_by_model(
    model: ConflictModel | None, urls: Sequence[str | None], reasons: Sequence[str | None]
) -> list[str | None]:
    """The rules' reasons, with NOT_CONFLICT for kept events whose headline the model finds
    unlike armed conflict. Events with no headline to read, or a headline with a word of war,
    stay as they were: the model misreads some of those ("US strikes Konarak base with
    Hellfire missiles", "fresh clashes rock Paris and Milan")."""
    reasons = list(reasons)
    if model is None:
        return reasons
    todo = []
    for i, (url, reason) in enumerate(zip(urls, reasons, strict=True)):
        headline = headline_words(url) if url and reason is None else []
        if len(headline) >= MIN_HEADLINE_WORDS and not _has(headline, WAR_PREFIXES, CONFLICT_WORDS):
            todo.append((i, " ".join(headline)))
    probabilities = model.conflict_probabilities([h for _, h in todo])
    for (i, _), p in zip(todo, probabilities, strict=True):
        if p < model.threshold:
            reasons[i] = NOT_CONFLICT
    return reasons


def _has(words: list[str], prefixes: tuple[str, ...], whole: set[str]) -> bool:
    return any(w in whole or w.startswith(prefixes) for w in words)


def rescreen(db: Session | Connection, model: ConflictModel | None = None) -> dict[str | None, int]:
    """Screens every stored violent GDELT event again, after the rules or the model change;
    returns how many events each reason (None: kept) now covers. The caller commits.

    Migration 0011 runs this, with the rules alone, to fill the column in, so it takes a
    plain connection too. With a model, the read is committed before the model runs: on all
    of GDELT that takes minutes, longer than a hosted database keeps an idle transaction."""
    rows = db.execute(
        text(
            "SELECT id, source_url, tone, admin1, attributes->>'actor1_code',"
            " attributes->>'actor2_code', screened_out FROM events"
            " WHERE source = 'gdelt' AND is_violent"
        )
    ).all()
    if model is not None:
        db.commit()
    by_rules = [screen(url, tone, adm1, (a1, a2)) for _, url, tone, adm1, a1, a2, _ in rows]
    reasons = screen_by_model(model, [row[1] for row in rows], by_rules)
    counts: dict[str | None, int] = {}
    changes = []
    for row, reason in zip(rows, reasons, strict=True):
        counts[reason] = counts.get(reason, 0) + 1
        if reason != row[-1]:
            changes.append({"id": row[0], "reason": reason})
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
