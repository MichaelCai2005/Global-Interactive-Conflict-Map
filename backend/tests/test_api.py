from tests.builders import ucdp_csv, ucdp_row
from tests.test_ingest import load_sample


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_events_hide_duplicates_by_default(client, session, tmp_path):
    load_sample(session, tmp_path)
    page = client.get("/events").json()
    assert page["total"] == 4
    assert all(e["duplicate_of_id"] is None for e in page["items"])
    assert client.get("/events", params={"include_duplicates": True}).json()["total"] == 5


def test_event_filters(client, session, tmp_path):
    load_sample(session, tmp_path)

    def ids(**params):
        return sorted(
            e["source_event_id"] for e in client.get("/events", params=params).json()["items"]
        )

    assert ids(source="ucdp") == ["900001", "900002"]
    assert ids(violent=False) == ["3"]
    assert ids(event_type=["protest", "fight"]) == ["3", "6"]
    assert ids(country="testland", start="2022-03-01") == ["6", "900001", "900002"]
    assert ids(bbox="36,49,37,51") == ["3", "900001"]
    assert ids(end="2022-02-28") == ["3"]


def test_bad_filters_are_rejected(client):
    assert client.get("/events", params={"bbox": "1,2,3"}).status_code == 422
    assert (
        client.get("/events", params={"start": "2022-02-01", "end": "2022-01-01"}).status_code
        == 422
    )
    assert client.get("/events", params={"limit": 0}).status_code == 422


def test_event_detail_shows_both_sides_of_a_link(client, session, tmp_path):
    load_sample(session, tmp_path)
    ucdp_event = client.get("/events", params={"source": "ucdp", "bbox": "36,49,37,51"}).json()[
        "items"
    ][0]
    detail = client.get(f"/events/{ucdp_event['id']}").json()
    assert [d["event"]["source"] for d in detail["duplicates"]] == ["gdelt"]

    dup_id = detail["duplicates"][0]["event"]["id"]
    assert client.get(f"/events/{dup_id}").json()["duplicate_of"]["event"]["id"] == ucdp_event["id"]
    assert client.get("/events/999999").status_code == 404


def test_timeline_separates_signals_from_violence(client, session, tmp_path):
    load_sample(session, tmp_path)
    buckets = client.get("/timeline", params={"interval": "week", "country": "Testland"}).json()[
        "buckets"
    ]
    assert buckets == [
        {"period": "2022-02-14", "violent_events": 0, "signal_events": 1, "fatalities": 0},
        {"period": "2022-02-28", "violent_events": 3, "signal_events": 0, "fatalities": 10},
    ]


def test_upload_and_inspect_rejected_rows(client):
    csv = ucdp_csv([ucdp_row(), ucdp_row(id="2", best="-1")])
    response = client.post("/ingest/ucdp", files={"file": ("ged.csv", csv, "text/csv")})
    assert response.status_code == 201
    run = response.json()
    assert (run["inserted"], run["rejected"]) == (1, 1)

    [rejected] = client.get(f"/ingest-runs/{run['id']}/rejected").json()
    assert rejected["row_number"] == 3
    assert rejected["raw"]["id"] == "2"
    assert client.get("/ingest-runs").json()[0]["id"] == run["id"]


def test_upload_errors(client):
    assert (
        client.post("/ingest/acme", files={"file": ("a.csv", "x", "text/csv")}).status_code == 404
    )
    bad = client.post("/ingest/gdelt", files={"file": ("a.zip", b"not a zip", "application/zip")})
    assert bad.status_code == 422
    assert "BadZipFile" in bad.json()["detail"]["error"]
