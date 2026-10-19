from sqlalchemy import select

from app.ingest.loader import ingest_file
from app.models import Event, EventLink, RejectedRecord
from tests.builders import acled_csv, acled_row, gdelt_row, gdelt_tsv, ucdp_csv, ucdp_row


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content)
    return path


def load_sample(session, tmp_path):
    ucdp_run = ingest_file(
        session,
        "ucdp",
        write(
            tmp_path,
            "ged.csv",
            ucdp_csv(
                [
                    ucdp_row(),
                    ucdp_row(),  # exact duplicate row
                    ucdp_row(id="900002", where_prec="6", latitude="48.5", longitude="31.2"),
                    ucdp_row(id="900003", latitude="123"),
                ]
            ),
        ),
    )
    gdelt_run = ingest_file(
        session,
        "gdelt",
        write(
            tmp_path,
            "20220301.export.CSV",
            gdelt_tsv(
                [
                    gdelt_row(GLOBALEVENTID="1"),  # ~2 km from UCDP 900001, same day
                    gdelt_row(GLOBALEVENTID="2", NumMentions="10"),  # same incident again
                    gdelt_row(
                        GLOBALEVENTID="3", EventRootCode="14", EventCode="141", SQLDATE="20220220"
                    ),  # protest a week before
                    gdelt_row(GLOBALEVENTID="4", EventRootCode="04", EventCode="040"),
                    gdelt_row(
                        GLOBALEVENTID="5", ActionGeo_Type="0", ActionGeo_Lat="", ActionGeo_Long=""
                    ),
                    gdelt_row(GLOBALEVENTID="6", ActionGeo_Lat="10.0", ActionGeo_Long="10.0"),
                ]
            ),
        ),
    )
    return ucdp_run, gdelt_run


def test_ingest_counts_every_outcome(session, tmp_path):
    ucdp_run, gdelt_run = load_sample(session, tmp_path)

    assert ucdp_run.status == "succeeded", ucdp_run.error
    assert (ucdp_run.rows_read, ucdp_run.inserted, ucdp_run.merged_in_file, ucdp_run.rejected) == (
        4,
        2,
        1,
        1,
    )
    assert gdelt_run.status == "succeeded", gdelt_run.error
    assert gdelt_run.rows_read == 6
    assert gdelt_run.filtered_out == 1
    assert gdelt_run.rejected == 1
    assert gdelt_run.merged_in_file == 1
    assert gdelt_run.inserted == 3
    assert gdelt_run.cross_source_links == 1

    reasons = session.scalars(select(RejectedRecord.reasons).order_by(RejectedRecord.id)).all()
    assert any("latitude out of range" in r for r in reasons[0])


def test_news_report_is_linked_to_the_ucdp_event(session, tmp_path):
    load_sample(session, tmp_path)
    canonical = session.scalar(select(Event).where(Event.source_event_id == "900001"))
    duplicate = session.scalar(select(Event).where(Event.source_event_id == "1"))
    far_away = session.scalar(select(Event).where(Event.source_event_id == "6"))

    assert duplicate.duplicate_of_id == canonical.id
    assert duplicate.report_count == 10
    assert canonical.duplicate_of_id is None
    assert far_away.duplicate_of_id is None
    link = session.scalar(select(EventLink))
    assert 0 < link.distance_km < 3
    assert link.day_gap == 0


def test_reloading_the_same_files_changes_nothing(session, tmp_path):
    load_sample(session, tmp_path)
    before = session.scalar(select(Event.id).order_by(Event.id.desc()))
    ucdp_run, gdelt_run = load_sample(session, tmp_path)

    assert ucdp_run.inserted == 0 and ucdp_run.updated == 2
    assert gdelt_run.inserted == 0 and gdelt_run.updated == 3
    assert gdelt_run.cross_source_links == 0
    assert session.scalar(select(Event.id).order_by(Event.id.desc())) == before


def test_country_level_events_are_never_linked(session, tmp_path):
    ingest_file(session, "ucdp", write(tmp_path, "g.csv", ucdp_csv([ucdp_row(where_prec="6")])))
    run = ingest_file(session, "gdelt", write(tmp_path, "d.CSV", gdelt_tsv([gdelt_row()])))
    assert run.cross_source_links == 0


def test_unreadable_file_marks_the_run_failed(session, tmp_path):
    run = ingest_file(session, "ucdp", write(tmp_path, "bad.csv", "not,a,ged\n1,2,3\n"))
    assert run.status == "failed"
    assert "missing columns" in run.error
    assert session.scalar(select(Event)) is None


def test_acled_links_under_ucdp_and_above_gdelt(session, tmp_path):
    ingest_file(session, "ucdp", write(tmp_path, "ged.csv", ucdp_csv([ucdp_row()])))
    acled_run = ingest_file(
        session,
        "acled",
        write(
            tmp_path,
            "acled.csv",
            acled_csv(
                [
                    acled_row(),  # same clash UCDP recorded
                    acled_row(event_id_cnty="TST200", latitude="10.0", longitude="10.0"),
                    acled_row(event_id_cnty="TST300", event_type="Protests", fatalities="0"),
                ]
            ),
        ),
    )
    gdelt_run = ingest_file(
        session,
        "gdelt",
        write(
            tmp_path, "g.CSV", gdelt_tsv([gdelt_row(ActionGeo_Lat="10.01", ActionGeo_Long="10.0")])
        ),
    )
    events = {e.source_event_id: e for e in session.scalars(select(Event))}

    assert acled_run.status == "succeeded", acled_run.error
    assert (acled_run.inserted, acled_run.cross_source_links) == (3, 1)
    assert events["TST100"].duplicate_of_id == events["900001"].id
    assert events["TST300"].duplicate_of_id is None  # protests are signals, never linked
    # With no UCDP event nearby, the GDELT report attaches to the ACLED one.
    assert gdelt_run.cross_source_links == 1
    assert events["1000000001"].duplicate_of_id == events["TST200"].id
