"""Which of UCDP's three kinds of organized violence an event is, for every source.

UCDP sorts violence by who fought whom: a government against another state or an armed
group (state-based), armed groups against each other with no government side (non-state),
or a government or armed group against unarmed people (one-sided). ACLED and GDELT name
their sides too, so their violent events can be sorted the same way and the map can color
every source alike. For ACLED and GDELT this is an inference from how the source coded the
two sides, not a finding; an event whose sides do not settle it gets None ("unclear").

GDELT actor codes are three-letter parts: a country, then roles, e.g. "NGAMIL" is
Nigeria's military, "SYRREB" Syrian rebels, "CVL" civilians. A bare country ("RUS") stands
for that country acting as a state, but only abroad: at home it is mostly where the story
is datelined. ACLED gives each side's kind directly (inter1, inter2).
"""

from collections.abc import Callable
from typing import Literal

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app import countries

STATE_BASED = "state_based"
NON_STATE = "non_state"
ONE_SIDED = "one_sided"
CONFLICT_TYPES = (STATE_BASED, NON_STATE, ONE_SIDED)

Side = Literal["state", "armed", "unarmed"]

# CAMEO role codes. Police count as state forces, as UCDP counts them. Criminals (CRM) are
# neither armed group nor unarmed: in the news they are mostly ordinary crime, which UCDP
# leaves out, so they settle nothing.
STATE_ROLES = {"GOV", "MIL", "COP", "SPY"}
ARMED_ROLES = {"REB", "INS", "SEP", "UAF", "RAD"}
UNARMED_ROLES = {
    "AGR", "BUS", "CVL", "EDU", "ELI", "ENV", "HLH", "HRI", "JUD", "LAB", "LEG", "MED",
    "MNC", "MOD", "NGO", "OPP", "PTY", "REF", "SET",
    # Religions, which GDELT codes as roles: Muslims, Christians, Jews, Hindus, Buddhists.
    "REL", "MOS", "CHR", "JEW", "HIN", "BUD", "CTH", "SHI", "SUN",
}  # fmt: skip
# GDELT codes Palestinians as a country, but UCDP counts their armed groups as rebels.
NOT_STATES = {"PSE"}

# CAMEO codes that only a military fires: artillery and tanks (194), aerial weapons (195).
MILITARY_CODES = ("194", "195")
# CAMEO 20: unconventional mass violence, such as mass expulsion or mass killing.
MASS_VIOLENCE_ROOT = "20"

ACLED_SIDES: dict[str, Side] = {
    "State forces": "state",
    "External/Other forces": "state",
    "Rebel group": "armed",
    "Political militia": "armed",
    "Identity militia": "armed",
    "Rioters": "unarmed",
    "Protesters": "unarmed",
    "Civilians": "unarmed",
    # Older ACLED files number the kinds instead.
    "1": "state",
    "2": "armed",
    "3": "armed",
    "4": "armed",
    "5": "unarmed",
    "6": "unarmed",
    "7": "unarmed",
    "8": "state",
}


def gdelt_parts(code: str) -> tuple[str | None, set[str]]:
    """A GDELT actor code's country, if it starts with one, and its other parts."""
    parts = [code[i : i + 3] for i in range(0, len(code), 3)]
    country = parts[0] if countries.is_iso3(parts[0]) else None
    return country, set(parts[1:] if country else parts)


def gdelt_side(code: str | None) -> Side | None:
    """What kind of side a GDELT actor code is."""
    if not code:
        return None
    country, roles = gdelt_parts(code)
    if roles & STATE_ROLES:
        return "state"
    if roles & ARMED_ROLES:
        return "armed"
    if roles & UNARMED_ROLES:
        return "unarmed"
    if country and not roles and country not in NOT_STATES:
        return "state"
    return None


def classify_gdelt(
    cameo_code: str | None, actor1: str | None, actor2: str | None, where: str | None = None
) -> str | None:
    """The kind of a violent GDELT event from its CAMEO code, its two actor codes and the
    ISO3 code of the country it happened in."""
    side1, side2 = gdelt_side(actor1), gdelt_side(actor2)
    country1, roles1 = gdelt_parts(actor1) if actor1 else (None, set())
    country2, roles2 = gdelt_parts(actor2) if actor2 else (None, set())
    # A bare country at home ("the US" in a US story) is only where the news is; abroad it
    # is a state acting on another country's soil, like Russia in Ukraine.
    home1 = side1 == "state" and not roles1 and where in (country1, None)
    home2 = side2 == "state" and not roles2 and where in (country2, None)
    if (
        actor1
        and actor2
        and ((home1 and country2 in (country1, None)) or (home2 and country1 in (country2, None)))
    ):
        # A country at home against its own people or forces, or against someone of no
        # country ("police shot a man in the US"), says nothing about who fought whom.
        kind = None
    elif side1 and side2:
        kind = classify(side1, side2)
    elif side2 == "unarmed":
        # Unarmed people attacked by someone unnamed is still one-sided.
        kind = ONE_SIDED
    elif (
        "MIL" in roles1 | roles2
        or (side1 == "state" and not roles1 and not home1)
        or (side2 == "state" and not roles2 and not home2)
    ):
        # With only one side known, a military acting (an air strike, a raid) or a country
        # acting abroad is still war, while "the government" or police alone, or a country
        # at home, is just a news story.
        kind = STATE_BASED
    else:
        kind = None
    code = cameo_code or ""
    if code.startswith(MASS_VIOLENCE_ROOT) and kind != STATE_BASED:
        return ONE_SIDED
    if kind is None and code.startswith(MILITARY_CODES) and "unarmed" not in (side1, side2):
        return STATE_BASED
    return kind


def classify_acled(event_type: str, inter1: str | None, inter2: str | None) -> str | None:
    kind = classify(ACLED_SIDES.get(inter1 or ""), ACLED_SIDES.get(inter2 or ""))
    if kind is None and event_type == "violence_against_civilians":
        return ONE_SIDED
    return kind


def classify(source: Side | None, target: Side | None) -> str | None:
    """The kind of violence a source side did to a target side; None when unclear."""
    if source == "unarmed":
        # Civilians attacking someone, which none of the three kinds covers.
        return None
    if target == "unarmed":
        # Someone armed, or someone unnamed, attacking unarmed people.
        return ONE_SIDED
    sides = {source, target}
    if "state" in sides:
        # A state against a state or an armed group, or a state's forces acting alone.
        return STATE_BASED
    if sides == {"armed"}:
        return NON_STATE
    return None


# Each source's rule and the columns it reads, as SQL on the events table.
RULES: dict[str, tuple[Callable[..., str | None], list[str]]] = {
    "gdelt": (
        classify_gdelt,
        [
            "attributes->>'cameo_code'",
            "attributes->>'actor1_code'",
            "attributes->>'actor2_code'",
            "country_iso3",
        ],
    ),
    "acled": (classify_acled, ["event_type", "attributes->>'inter1'", "attributes->>'inter2'"]),
}


def reclassify(db: Session | Connection) -> dict[str | None, int]:
    """Sorts every stored violent ACLED and GDELT event again, after the rules change;
    returns how many events each kind (None: unclear) now covers. The caller commits.

    The kind depends only on a few columns, so each distinct combination is sorted once
    and written back with one UPDATE per source. Migration 0010 runs this to fill the
    column in, so it takes a plain connection too."""
    counts: dict[str | None, int] = {}
    for source, (rule, columns) in RULES.items():
        keys = [f"coalesce({c}, '')" for c in columns]
        names = [f"k{i}" for i in range(len(keys))]
        combos = db.execute(
            text(
                f"SELECT {', '.join(keys)}, count(*) FROM events"
                f" WHERE source = :source AND is_violent"
                f" GROUP BY {', '.join(str(i + 1) for i in range(len(keys)))}"
            ),
            {"source": source},
        ).all()
        if not combos:
            continue
        rows = []
        for *values, n in combos:
            kind = rule(*(v or None for v in values))
            counts[kind] = counts.get(kind, 0) + n
            rows.append(dict(zip(names, values, strict=True)) | {"kind": kind})
        db.execute(
            text(
                f"CREATE TEMP TABLE conflict_types ({', '.join(f'{n} text' for n in names)}, kind text)"
            )
        )
        db.execute(
            text(f"INSERT INTO conflict_types VALUES ({', '.join(':' + n for n in names)}, :kind)"),
            rows,
        )
        matches = " AND ".join(f"{key} = t.{n}" for key, n in zip(keys, names, strict=True))
        db.execute(
            text(
                "UPDATE events SET conflict_type = t.kind FROM conflict_types t"
                f" WHERE source = :source AND is_violent AND {matches}"
                " AND conflict_type IS DISTINCT FROM t.kind"
            ),
            {"source": source},
        )
        db.execute(text("DROP TABLE conflict_types"))
    return counts
