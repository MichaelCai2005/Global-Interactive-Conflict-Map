from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text

from app.boards.models import Board, BoardLink, BoardNode, Observation
from app.config import get_settings
from app.main import app
from app.models import EventLink, IngestRun, WatchItem
from app.publish import copy_database, licence_problems
from tests.conftest import TEST_DATABASE_URL
from tests.test_boards import add_event


@pytest.fixture
def settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_token", None)
    monkeypatch.setattr(settings, "public_mode", False)
    return settings


WATCH = {"name": "Donbas", "bbox": "36,47,40,50"}


def test_writes_are_open_locally_without_a_token(client, settings):
    assert client.post("/watchlist", json=WATCH).status_code == 201


def test_admin_token_guards_every_write(client, settings):
    settings.admin_token = "s3cret"
    assert client.post("/watchlist", json=WATCH).status_code == 401
    assert client.post("/boards", json={"title": "x"}).status_code == 401
    assert client.delete("/watchlist/1").status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert client.post("/watchlist", json=WATCH, headers=wrong).status_code == 401
    unicode = {"X-Admin-Token": "s3crét".encode()}
    assert client.post("/watchlist", json=WATCH, headers=unicode).status_code == 401

    bearer = {"Authorization": "Bearer s3cret"}
    assert client.post("/watchlist", json=WATCH, headers=bearer).status_code == 201
    header = {"X-Admin-Token": "s3cret"}
    assert client.post("/watchlist", json=WATCH, headers=header).status_code == 201
    assert len(client.get("/watchlist").json()) == 2


def test_public_mode_is_read_only_without_a_token(client, settings):
    settings.public_mode = True
    assert client.get("/watchlist").status_code == 200
    refused = client.post("/watchlist", json=WATCH)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "this deployment is read-only"


def test_public_mode_refuses_acled_uploads_even_with_the_token(client, settings):
    settings.public_mode, settings.admin_token = True, "s3cret"
    files = {"file": ("acled.csv", b"event_id_cnty\n", "text/csv")}
    response = client.post("/ingest/acled", files=files, headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 403


def _run(session, source):
    run = IngestRun(source=source, filename=f"{source}.csv", status="succeeded")
    session.add(run)
    session.flush()
    return run


def test_public_api_will_not_start_on_acled_data(session, settings):
    add_event(session, _run(session, "acled"), "a1", latitude=15.0, longitude=-1.0,
              event_date=date(2024, 3, 1))  # fmt: skip
    session.commit()
    assert licence_problems(session.connection()) == ["events from acled"]

    settings.public_mode = True
    with pytest.raises(RuntimeError, match="events from acled"), TestClient(app):
        pass


@pytest.fixture
def target_url(engine):
    """An empty second database to publish into, dropped afterwards."""
    url = make_url(TEST_DATABASE_URL)
    name = f"{url.database}_publish"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        try:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"cannot create a scratch database: {e}")
    yield url.set(database=name).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def test_copy_leaves_acled_behind(session, target_url):
    ucdp, acled, gdelt = _run(session, "ucdp"), _run(session, "acled"), _run(session, "gdelt")
    day = date(2024, 3, 1)
    where = dict(latitude=15.0, longitude=-1.0, event_date=day)
    u = add_event(session, ucdp, "u1", source="ucdp", **where)
    a = add_event(session, acled, "a1", duplicate_of_id=u.id, **where)
    a2 = add_event(session, acled, "a2", **where)
    g = add_event(session, gdelt, "g1", source="gdelt", duplicate_of_id=a2.id, **where)
    old = add_event(session, gdelt, "g0", source="gdelt", latitude=15.0, longitude=-1.0,
                    event_date=date(2001, 5, 1))  # fmt: skip
    session.add_all(
        [
            EventLink(event_id=u.id, related_event_id=a.id, link_type="duplicate",
                      distance_km=1, day_gap=0, score=1),
            EventLink(event_id=u.id, related_event_id=g.id, link_type="corroborates",
                      distance_km=1, day_gap=0, score=0.5),
        ]
    )  # fmt: skip
    board = Board(title="Mali", origin="topic")
    session.add(board)
    session.flush()
    common = dict(board_id=board.id, kind="event", created_by="rule")
    nodes = [
        BoardNode(key="u", label="UCDP event", event_id=u.id, source_name="UCDP GED", **common),
        BoardNode(key="a", label="ACLED event", event_id=a2.id, **common),
        BoardNode(key="cited", label="Cited", source_name="ACLED", **common),
        BoardNode(key="old", label="Old report", event_id=old.id, **common),
    ]
    session.add_all(nodes)
    session.flush()
    common = dict(board_id=board.id, reason="r", confidence=1, created_by="rule")
    session.add_all(
        [
            BoardLink(from_node_id=nodes[0].id, to_node_id=nodes[3].id, rule="place", **common),
            BoardLink(from_node_id=nodes[0].id, to_node_id=nodes[1].id, rule="place", **common),
        ]
    )
    session.add(Observation(source="adsb", kind="flight", external_id="ae01",
                            observed_at=day, latitude=15.0, longitude=-1.0))  # fmt: skip
    session.add(WatchItem(name="Private note", country="Mali"))
    session.commit()

    copy_database(TEST_DATABASE_URL, target_url)
    target = create_engine(target_url)
    with target.connect() as conn:
        rows = conn.execute(
            text("SELECT dedupe_key, duplicate_of_id FROM events ORDER BY dedupe_key")
        ).all()
        # g1's canonical twin was ACLED, so it is canonical now and shows on the map.
        assert rows == [("g0", None), ("g1", None), ("u1", None)]
        assert conn.execute(text("SELECT link_type FROM event_links")).scalars().all() == [
            "corroborates"
        ]
        assert conn.execute(text("SELECT key FROM board_nodes ORDER BY key")).scalars().all() == [
            "old",
            "u",
        ]
        assert conn.execute(text("SELECT count(*) FROM board_links")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM observations")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM watch_items")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM ingest_runs")).scalar() == 2
        assert licence_problems(conn) == []
        # New rows get fresh ids instead of colliding with copied ones.
        new_id = conn.execute(
            text("INSERT INTO boards (title, origin, prompt, notes) VALUES ('n', 'topic', '', '')"
                 " RETURNING id")
        ).scalar()  # fmt: skip
        assert new_id == board.id + 1

    with pytest.raises(SystemExit, match="--replace"):
        copy_database(TEST_DATABASE_URL, target_url)

    copy_database(TEST_DATABASE_URL, target_url, since=date(2010, 1, 1), replace=True)
    with target.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM events")).scalar() == 2
        # The node on the dropped event keeps its text and loses the event.
        assert (
            conn.execute(text("SELECT event_id FROM board_nodes WHERE key = 'old'")).scalar()
            is None
        )
    target.dispose()
