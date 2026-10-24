"""World Bank World Development Indicators, as saved by `ingest download wdi`.

The World Bank API returns one JSON record per country, year and indicator; the downloader
writes them to a CSV with the API's own field names: indicator, countryiso3code, date, value.
Rows for regions and income groups (AFE, WLD, HIC...) are filtered out, as are years the
World Bank has no estimate for.
API docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
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

SOURCE = "wdi"

REQUIRED_COLUMNS = {"indicator", "countryiso3code", "date", "value"}

# Economic shocks, poverty, state capacity, demographics and resources, in the order of the
# conflict-drivers table. Infant mortality is the classic proxy for state capacity.
INDICATORS = {
    "NY.GDP.PCAP.KD": "GDP per capita (constant 2015 US$)",
    "NY.GDP.MKTP.KD.ZG": "GDP growth (annual %)",
    "FP.CPI.TOTL.ZG": "Inflation, consumer prices (annual %)",
    "SL.UEM.TOTL.ZS": "Unemployment (% of labour force, modelled ILO estimate)",
    "SP.DYN.IMRT.IN": "Infant mortality (per 1,000 live births)",
    "SP.POP.TOTL": "Population, total",
    "SP.URB.TOTL.IN.ZS": "Urban population (% of total)",
    "NY.GDP.TOTL.RT.ZS": "Total natural resource rents (% of GDP)",
    "MS.MIL.XPND.GD.ZS": "Military expenditure (% of GDP)",
}


def parse(stream: TextIO) -> Iterator[ParsedIndicatorRow]:
    reader = csv.DictReader(stream)
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"not a WDI download, missing columns: {sorted(missing)}")
    for row_number, raw in enumerate(reader, start=2):
        yield parse_row(row_number, raw)


def parse_row(row_number: int, raw: dict[str, str]) -> ParsedIndicatorRow:
    errors = FieldErrors()
    indicator = errors.require(clean_text(raw.get("indicator")), "indicator")
    code = clean_text(raw.get("countryiso3code"))
    year = errors.require(errors.take(parse_int, raw.get("date"), "date"), "date")
    value = errors.take(parse_float, raw.get("value"), "value")
    if year is not None and year < EARLIEST_DATE.year:
        errors.append(f"year before {EARLIEST_DATE.year}: {year}")
    if errors:
        return ParsedIndicatorRow(row_number, raw, reasons=list(errors))
    if value is None or not countries.is_iso3(code):
        return ParsedIndicatorRow(row_number, raw, filtered_out=True)
    return ParsedIndicatorRow(
        row_number, raw, values=[IndicatorValue(indicator, code, year, value)]
    )
