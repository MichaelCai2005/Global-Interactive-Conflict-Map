"""Country code crosswalk: maps each source's own country codes to ISO 3166 alpha-3.

Every source names countries differently: UCDP and EPR use Gleditsch-Ward numbers, ACLED
ISO numeric codes, GDELT FIPS 10-4 codes, V-Dem its own ids. Events and indicators are all
stored with ISO3 so they can be joined.

data/countries.csv comes from the countrycode package's codelist
(https://github.com/vincentarelbundock/countrycode), with these additions:
  - Kosovo as XKX, the code the World Bank and V-Dem use (it has no official ISO code)
  - Gleditsch-Ward 345 (Yugoslavia) as Serbia and 678 (Yemen Arab Republic) as Yemen,
    because UCDP and EPR code the successor states that way; 816 as Vietnam
  - FIPS GZ (Gaza) as Palestine, RB as Serbia and OD as South Sudan, as GDELT uses them
Where a country has several codes in one scheme, the first is its primary code.
Historical states with no successor (East Germany, South Vietnam) are left unmapped.
"""

import csv
from dataclasses import dataclass
from functools import cache
from pathlib import Path

CROSSWALK = Path(__file__).parent / "data" / "countries.csv"


@dataclass(frozen=True)
class Country:
    iso3: str
    name: str
    iso_numeric: tuple[str, ...]
    fips: tuple[str, ...]
    gw: tuple[str, ...]
    vdem: tuple[str, ...]


@cache
def all_countries() -> dict[str, Country]:
    with CROSSWALK.open(encoding="utf-8", newline="") as f:
        return {
            row["iso3"]: Country(
                iso3=row["iso3"],
                name=row["name"],
                iso_numeric=tuple(row["iso_numeric"].split()),
                fips=tuple(row["fips"].split()),
                gw=tuple(row["gw"].split()),
                vdem=tuple(row["vdem"].split()),
            )
            for row in csv.DictReader(f)
        }


@cache
def _index(scheme: str) -> dict[str, str]:
    index: dict[str, str] = {}
    for country in all_countries().values():
        for code in getattr(country, scheme):
            if index.setdefault(code, country.iso3) != country.iso3:
                raise ValueError(f"{scheme} code {code} maps to {index[code]} and {country.iso3}")
    return index


def _numeric(value: str | None) -> str | None:
    """'004', '4' and '4.0' are the same code."""
    try:
        return str(int(float(value.strip()))) if value and value.strip() else None
    except ValueError:
        return None


def from_gw(code: str | None) -> str | None:
    return _index("gw").get(_numeric(code) or "")


def from_iso_numeric(code: str | None) -> str | None:
    return _index("iso_numeric").get(_numeric(code) or "")


def from_fips(code: str | None) -> str | None:
    return _index("fips").get((code or "").strip().upper())


def from_vdem(code: str | None) -> str | None:
    return _index("vdem").get(_numeric(code) or "")


def is_iso3(code: str | None) -> bool:
    return code in all_countries()


def is_primary_gw(code: str, iso3: str) -> bool:
    country = all_countries().get(iso3)
    return bool(country and country.gw and country.gw[0] == _numeric(code))
