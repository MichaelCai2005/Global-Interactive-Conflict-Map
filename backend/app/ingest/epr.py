"""Ethnic Power Relations (EPR) Core dataset.

EPR lists every politically relevant ethnic group in each country, with its share of the
population and its access to state power, in periods of years (one row per group and
period). This module turns those rows into country-year totals:

  excluded_pop_share       population share of groups shut out of power (powerless,
                           discriminated or self-excluded)
  discriminated_pop_share  population share of groups actively discriminated against
  excluded_groups          number of excluded groups
  groups_in_power          number of groups that rule alone or share power

A country-year whose groups are all irrelevant or under state collapse gets zeros.
Countries are coded with Gleditsch-Ward numbers. When a state's code changes mid-year
(Yugoslavia, 345, became Serbia, 340, in 2006), both codes cover that year, so only the
country's primary code is kept for it.
Codebook: https://icr.ethz.ch/data/epr/core/
"""

import csv
from collections import defaultdict
from collections.abc import Iterator
from typing import TextIO

from app import countries
from app.ingest.common import (
    EARLIEST_DATE,
    FieldErrors,
    IndicatorValue,
    ParsedIndicatorRow,
    clean_text,
    parse_float,
    parse_int,
)

SOURCE = "epr"

REQUIRED_COLUMNS = {"gwid", "statename", "from", "to", "group", "size", "status"}

INDICATORS = {
    "excluded_pop_share": "Population share of ethnic groups excluded from power (0 to 1)",
    "discriminated_pop_share": "Population share of ethnic groups discriminated against (0 to 1)",
    "excluded_groups": "Number of politically relevant ethnic groups excluded from power",
    "groups_in_power": "Number of ethnic groups ruling alone or sharing power",
}

IN_POWER = {"MONOPOLY", "DOMINANT", "SENIOR PARTNER", "JUNIOR PARTNER"}
EXCLUDED = {"POWERLESS", "DISCRIMINATED", "SELF-EXCLUSION"}
STATUSES = IN_POWER | EXCLUDED | {"IRRELEVANT", "STATE COLLAPSE"}


def parse(stream: TextIO) -> Iterator[ParsedIndicatorRow]:
    reader = csv.DictReader(stream)
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"not an EPR Core file, missing columns: {sorted(missing)}")

    rows: list[ParsedIndicatorRow] = []
    # (gw code, year) -> measure -> total, and the row each country-year's totals travel on.
    totals: dict[tuple[str, int], dict[str, float]] = defaultdict(
        lambda: dict.fromkeys(INDICATORS, 0.0)
    )
    first_row: dict[tuple[str, int], ParsedIndicatorRow] = {}
    for row_number, raw in enumerate(reader, start=2):
        row, group = parse_row(row_number, raw)
        rows.append(row)
        if group is None:
            continue
        gw, start, end, size, status = group
        for year in range(max(start, EARLIEST_DATE.year), end + 1):
            measures = totals[gw, year]
            first_row.setdefault((gw, year), row)
            if status in EXCLUDED:
                measures["excluded_pop_share"] += size
                measures["excluded_groups"] += 1
            if status == "DISCRIMINATED":
                measures["discriminated_pop_share"] += size
            if status in IN_POWER:
                measures["groups_in_power"] += 1

    # One code per country-year: the primary one when two codes cover the same year.
    chosen: dict[tuple[str, int], str] = {}
    for gw, year in totals:
        iso3 = countries.from_gw(gw)
        if (iso3, year) not in chosen or countries.is_primary_gw(gw, iso3):
            chosen[iso3, year] = gw
    for (iso3, year), gw in chosen.items():
        measures = totals[gw, year]
        first_row[gw, year].values += [
            # Shares are summed from rounded group sizes, so they can drift a hair past 1.
            IndicatorValue(
                name, iso3, year, min(round(value, 6), 1.0) if "share" in name else value
            )
            for name, value in measures.items()
        ]
    yield from rows


def parse_row(
    row_number: int, raw: dict[str, str]
) -> tuple[ParsedIndicatorRow, tuple[str, int, int, float, str] | None]:
    errors = FieldErrors()
    gw = errors.require(errors.take(parse_int, raw.get("gwid"), "gwid"), "gwid")
    start = errors.require(errors.take(parse_int, raw.get("from"), "from"), "from")
    end = errors.require(errors.take(parse_int, raw.get("to"), "to"), "to")
    size = errors.require(errors.take(parse_float, raw.get("size"), "size"), "size")
    status = clean_text(raw.get("status"))
    if status not in STATUSES:
        errors.append(f"unknown status: {status!r}")
    if start is not None and end is not None and end < start:
        errors.append(f"period ends ({end}) before it starts ({start})")
    if size is not None and not 0 <= size <= 1:
        errors.append(f"group size outside 0 to 1: {size}")
    if errors:
        return ParsedIndicatorRow(row_number, raw, reasons=list(errors)), None
    if countries.from_gw(str(gw)) is None or end < EARLIEST_DATE.year:
        return ParsedIndicatorRow(row_number, raw, filtered_out=True), None
    return ParsedIndicatorRow(row_number, raw), (str(gw), start, end, size, status)
