"""V-Dem Country-Year Core CSVs.

V-Dem (Varieties of Democracy) scores every country's regime each year from expert surveys.
Its downloads sit behind a registration form, so there is no downloader: get
"Country-Year: V-Dem Core" as CSV from https://v-dem.net/data/the-v-dem-dataset/ and load
the file (or its zip) directly. The Full+Others file works too, since it has the same columns.

Each row is one country-year carrying every index; the ones in INDICATORS are kept. A file
needs at least one of them. Countries are matched on V-Dem's numeric country_id first, then
on country_text_id, which is ISO3 for most present-day countries. Historical states (Baden,
South Vietnam...) are filtered out.
Codebook: https://v-dem.net/data/reference-documents/
"""

import csv
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

SOURCE = "vdem"

REQUIRED_COLUMNS = {"country_id", "country_text_id", "year"}

INDICATORS = {
    "v2x_polyarchy": "Electoral democracy index (0 to 1)",
    "v2x_libdem": "Liberal democracy index (0 to 1)",
    "v2x_regime": "Regimes of the World: 0 closed autocracy, 1 electoral autocracy, "
    "2 electoral democracy, 3 liberal democracy",
    "v2x_civlib": "Civil liberties index (0 to 1)",
    "v2x_clphy": "Physical violence index: freedom from political killings and torture (0 to 1)",
    "v2x_corr": "Political corruption index (0 to 1, higher is more corrupt)",
    "v2x_rule": "Rule of law index (0 to 1)",
}

# V-Dem writes missing values as empty cells in its CSVs and "NA" in some exports.
_MISSING = {"", "NA"}


def parse(stream: TextIO) -> Iterator[ParsedIndicatorRow]:
    reader = csv.DictReader(stream)
    columns = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise ValueError(f"not a V-Dem country-year file, missing columns: {sorted(missing)}")
    present = [c for c in INDICATORS if c in columns]
    if not present:
        raise ValueError(f"V-Dem file has none of the indicators {sorted(INDICATORS)}")
    for row_number, raw in enumerate(reader, start=2):
        yield parse_row(row_number, raw, present)


def parse_row(row_number: int, raw: dict[str, str], indicators: list[str]) -> ParsedIndicatorRow:
    errors = FieldErrors()
    year = errors.require(errors.take(parse_int, raw.get("year"), "year"), "year")
    values = {}
    for name in indicators:
        cell = (raw.get(name) or "").strip()
        if cell not in _MISSING:
            values[name] = errors.take(parse_float, cell, name)
    if errors:
        return ParsedIndicatorRow(row_number, raw, reasons=list(errors))

    text_id = clean_text(raw.get("country_text_id"))
    iso3 = countries.from_vdem(raw.get("country_id")) or (
        text_id if countries.is_iso3(text_id) else None
    )
    # V-Dem goes back to 1789; this project starts where its event data can.
    if iso3 is None or year < EARLIEST_DATE.year or not values:
        return ParsedIndicatorRow(row_number, raw, filtered_out=True)
    return ParsedIndicatorRow(
        row_number, raw, values=[IndicatorValue(k, iso3, year, v) for k, v in values.items()]
    )
