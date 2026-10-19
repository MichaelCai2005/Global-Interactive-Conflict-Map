"""Builds rows in each source's real file layout for tests.

These are synthetic test rows, not real events. Each builder starts from one valid row
and lets a test override only the fields it cares about.
"""

import csv
import io

from app.ingest import gdelt

UCDP_COLUMNS = [
    "id", "relid", "year", "active_year", "code_status", "type_of_violence",
    "conflict_dset_id", "conflict_new_id", "conflict_name", "dyad_dset_id", "dyad_new_id",
    "dyad_name", "side_a_dset_id", "side_a_new_id", "side_a", "side_b_dset_id",
    "side_b_new_id", "side_b", "number_of_sources", "source_article", "source_office",
    "source_date", "source_headline", "source_original", "where_prec", "where_coordinates",
    "where_description", "adm_1", "adm_2", "latitude", "longitude", "geom_wkt",
    "priogrid_gid", "country", "country_id", "region", "event_clarity", "date_prec",
    "date_start", "date_end", "deaths_a", "deaths_b", "deaths_civilians", "deaths_unknown",
    "best", "high", "low", "gwnoa", "gwnob",
]  # fmt: skip


def ucdp_row(**overrides) -> dict[str, str]:
    row = dict.fromkeys(UCDP_COLUMNS, "")
    row.update(
        id="900001",
        type_of_violence="1",
        conflict_new_id="11111",
        conflict_name="Testland: Government",
        side_a="Government of Testland",
        side_b="Test Liberation Front",
        number_of_sources="3",
        where_prec="1",
        where_coordinates="Testville town",
        adm_1="North province",
        latitude="49.990",
        longitude="36.230",
        country="Testland (Old Testland)",
        date_start="2022-03-01 00:00:00.000",
        date_end="2022-03-01 00:00:00.000",
        best="5",
        low="3",
        high="8",
    )
    row.update({k: str(v) for k, v in overrides.items()})
    return row


def ucdp_csv(rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=UCDP_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def gdelt_row(layout: int = 58, **overrides) -> list[str]:
    row = dict.fromkeys(gdelt.LAYOUTS[layout], "")
    row.update(
        GLOBALEVENTID="1000000001",
        SQLDATE="20220301",
        Actor1Code="TSTMIL",
        Actor1Name="TESTLAND",
        Actor2Code="TSTREB",
        Actor2Name="REBEL",
        IsRootEvent="1",
        EventCode="190",
        EventBaseCode="190",
        EventRootCode="19",
        QuadClass="4",
        GoldsteinScale="-10.0",
        NumMentions="4",
        NumSources="2",
        NumArticles="4",
        AvgTone="-6.5",
        ActionGeo_Type="4",
        ActionGeo_FullName="Testville, North province, Testland",
        ActionGeo_CountryCode="TS",
        ActionGeo_ADM1Code="TS01",
        ActionGeo_Lat="49.98",
        ActionGeo_Long="36.25",
        DATEADDED="20220302",
        SOURCEURL="https://news.example/testville",
    )
    row.update({k: str(v) for k, v in overrides.items() if k in row})
    return list(row.values())


def gdelt_tsv(rows: list[list[str]]) -> str:
    return "".join("\t".join(r) + "\n" for r in rows)
