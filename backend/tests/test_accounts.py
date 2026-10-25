"""Accounts: signing up and in, and each person seeing only their own data (app.auth)."""

import pytest
from sqlalchemy import func, select

from app import auth
from app.boards.models import Board
from app.config import get_settings
from app.models import SavedSearch, User, UserSession, WatchItem

PASSWORD = "correct horse battery"
WATCH = {"name": "Donbas", "bbox": "36,47,40,50"}


@pytest.fixture
def settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_token", None)
    monkeypatch.setattr(settings, "public_mode", True)
    monkeypatch.setattr(settings, "signups_open", True)
    monkeypatch.setattr(settings, "secure_cookies", False)  # TestClient talks plain http
    auth.failed_logins.clear()
    auth.signups.clear()
    return settings


def sign_up(client, email="ana@example.org", password=PASSWORD):
    client.cookies.clear()
    response = client.post("/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


def test_passwords_are_hashed_and_checked():
    stored = auth.hash_password(PASSWORD)
    assert PASSWORD not in stored and stored.startswith("scrypt$")
    assert auth.verify_password(PASSWORD, stored)
    assert not auth.verify_password("wrong password", stored)
    assert not auth.verify_password(PASSWORD, "garbage")
    assert auth.hash_password(PASSWORD) != stored  # salted


def test_sign_up_sign_in_and_out(client, session, settings):
    assert client.get("/auth/me").json() == {
        "user": None,
        "workspace": None,
        "signups_open": True,
    }
    me = sign_up(client, email="  Ana@Example.org ")
    assert me["user"]["email"] == "ana@example.org"
    assert me["workspace"] == "personal"
    cookie = client.cookies[auth.COOKIE]
    # The database keeps only a hash of the cookie's token.
    stored = session.scalar(select(UserSession.token_hash))
    assert stored != cookie and len(stored) == 64
    assert client.get("/auth/me").json()["user"]["email"] == "ana@example.org"

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").json()["user"] is None
    assert session.scalar(select(func.count()).select_from(UserSession)) == 0

    wrong = client.post("/auth/login", json={"email": "ana@example.org", "password": "nope"})
    assert wrong.status_code == 401
    unknown = client.post("/auth/login", json={"email": "bo@example.org", "password": PASSWORD})
    assert unknown.json()["detail"] == wrong.json()["detail"]
    ok = client.post("/auth/login", json={"email": "ANA@example.org", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["user"]["email"] == "ana@example.org"


def test_sign_up_checks_its_input(client, settings):
    sign_up(client)
    again = client.post("/auth/signup", json={"email": "ANA@example.org", "password": PASSWORD})
    assert again.status_code == 409
    short = client.post("/auth/signup", json={"email": "c@example.org", "password": "short"})
    assert short.status_code == 422
    bad = client.post("/auth/signup", json={"email": "not-an-email", "password": PASSWORD})
    assert bad.status_code == 422
    settings.signups_open = False
    closed = client.post("/auth/signup", json={"email": "d@example.org", "password": PASSWORD})
    assert closed.status_code == 403


def test_repeated_failed_sign_ins_are_slowed_down(client, settings):
    sign_up(client)
    client.cookies.clear()
    body = {"email": "ana@example.org", "password": "wrong guess"}
    codes = [client.post("/auth/login", json=body).status_code for _ in range(11)]
    assert codes == [401] * 10 + [429]
    # Even the right password waits until the window passes.
    right = client.post("/auth/login", json={**body, "password": PASSWORD})
    assert right.status_code == 429


def test_an_expired_sign_in_no_longer_counts(client, session, settings):
    sign_up(client)
    row = session.scalar(select(UserSession))
    row.expires_at = row.created_at
    session.commit()
    assert client.get("/auth/me").json()["user"] is None
    assert client.get("/watchlist").status_code == 401


def test_each_person_sees_only_their_own_watchlist_and_tasks(client, settings):
    assert client.get("/watchlist").status_code == 401
    assert client.post("/watchlist", json=WATCH).status_code == 401

    sign_up(client, "ana@example.org")
    mine = client.post("/watchlist", json=WATCH).json()
    task = client.post("/tasks", json={"title": "Check", "watch_item_id": mine["id"]})
    assert task.status_code == 201

    sign_up(client, "bo@example.org")
    assert client.get("/watchlist").json() == []
    assert client.get("/tasks").json() == []
    assert client.patch(f"/watchlist/{mine['id']}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/watchlist/{mine['id']}").status_code == 404
    assert client.delete(f"/tasks/{task.json()['id']}").status_code == 404
    # Nor can a task point at someone else's watch item.
    theirs = client.post("/tasks", json={"title": "Sneak", "watch_item_id": mine["id"]})
    assert theirs.status_code == 404

    client.post("/auth/login", json={"email": "ana@example.org", "password": PASSWORD})
    assert [w["name"] for w in client.get("/watchlist").json()] == ["Donbas"]
    assert len(client.get("/tasks").json()) == 1


def test_a_local_install_keeps_its_shared_workspace(client, session, settings):
    settings.public_mode = False
    assert client.post("/watchlist", json=WATCH).status_code == 201
    assert client.get("/auth/me").json()["workspace"] == "shared"
    # Signing in on a local install switches to that person's own workspace.
    sign_up(client)
    assert client.get("/watchlist").json() == []
    assert client.post("/watchlist", json={"name": "Sahel", "country": "Mali"}).status_code == 201
    client.cookies.clear()
    assert [w["name"] for w in client.get("/watchlist").json()] == ["Donbas"]
    owners = session.execute(select(WatchItem.name, WatchItem.user_id)).all()
    assert {name: owner is None for name, owner in owners} == {"Donbas": True, "Sahel": False}


def test_boards_are_private_to_their_owner_and_shared_ones_are_read_only(client, session, settings):
    shared = Board(title="Showcase", origin="manual")
    session.add(shared)
    session.commit()

    assert [b["title"] for b in client.get("/boards").json()] == ["Showcase"]
    assert client.post("/boards", json={"title": "Mine"}).status_code == 401

    sign_up(client, "ana@example.org")
    mine = client.post("/boards", json={"title": "Mine"}).json()
    assert {b["title"] for b in client.get("/boards").json()} == {"Showcase", "Mine"}
    assert client.patch(f"/boards/{mine['id']}", json={"title": "Renamed"}).status_code == 200
    assert client.get(f"/boards/{shared.id}").status_code == 200
    edit_shared = client.patch(f"/boards/{shared.id}", json={"title": "Mine now"})
    assert edit_shared.status_code == 403
    assert client.delete(f"/boards/{shared.id}").status_code == 403

    sign_up(client, "bo@example.org")
    assert [b["title"] for b in client.get("/boards").json()] == ["Showcase"]
    assert client.get(f"/boards/{mine['id']}").status_code == 404
    assert client.get(f"/boards/{mine['id']}/geojson").status_code == 404
    assert client.delete(f"/boards/{mine['id']}").status_code == 404

    client.cookies.clear()
    assert client.get(f"/boards/{mine['id']}").status_code == 404
    assert client.get(f"/boards/{shared.id}/geojson").status_code == 200


def test_saved_searches(client, session, settings):
    assert client.get("/searches").status_code == 401
    sign_up(client, "ana@example.org")
    view = {"name": "Sudan this year", "kind": "map", "params": {"query": "country=Sudan"}}
    saved = client.post("/searches", json=view)
    assert saved.status_code == 201
    first = saved.json()
    client.post("/searches", json={"name": "Later", "kind": "map", "params": {}})
    assert [s["name"] for s in client.get("/searches").json()] == ["Later", "Sudan this year"]

    used = client.patch(f"/searches/{first['id']}", json={"used": True}).json()
    assert used["last_used_at"] is not None
    assert client.get("/searches").json()[0]["name"] == "Sudan this year"
    assert client.get("/searches", params={"kind": "topic"}).json() == []
    bad = client.post("/searches", json={"name": "x", "kind": "nope", "params": {}})
    assert bad.status_code == 422

    sign_up(client, "bo@example.org")
    assert client.get("/searches").json() == []
    assert client.delete(f"/searches/{first['id']}").status_code == 404
    client.post("/auth/login", json={"email": "ana@example.org", "password": PASSWORD})
    assert client.delete(f"/searches/{first['id']}").status_code == 204


def test_topic_searches_are_remembered_once_each(session):
    from app.api.searches import record_topic

    owner = auth.Workspace(None)
    record_topic(session, owner, {"topic": "Port Sudan drones", "days": 14})
    record_topic(session, owner, {"topic": "port sudan drones", "days": 30})
    session.commit()
    rows = session.scalars(select(SavedSearch)).all()
    assert len(rows) == 1
    assert rows[0].kind == "topic" and rows[0].params["days"] == 30


def test_changing_the_password_signs_out_other_browsers(client, settings):
    sign_up(client)
    other = client.cookies[auth.COOKIE]
    client.cookies.clear()
    client.post("/auth/login", json={"email": "ana@example.org", "password": PASSWORD})

    wrong = client.patch(
        "/auth/me", json={"new_password": "new password 1", "current_password": "x"}
    )
    assert wrong.status_code == 403
    changed = client.patch(
        "/auth/me",
        json={
            "new_password": "new password 1",
            "current_password": PASSWORD,
            "display_name": "Ana",
        },
    )
    assert changed.status_code == 200 and changed.json()["display_name"] == "Ana"
    assert client.get("/auth/me").json()["user"] is not None
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, other)
    assert client.get("/auth/me").json()["user"] is None


def test_deleting_an_account_deletes_its_data(client, session, settings):
    sign_up(client)
    client.post("/watchlist", json=WATCH)
    client.post("/boards", json={"title": "Mine"})
    client.post("/searches", json={"name": "v", "kind": "map", "params": {}})
    assert client.request("DELETE", "/auth/me", json={"password": "nope"}).status_code == 403
    assert client.request("DELETE", "/auth/me", json={"password": PASSWORD}).status_code == 204
    session.expire_all()
    for model in (User, WatchItem, Board, SavedSearch, UserSession):
        assert session.scalar(select(func.count()).select_from(model)) == 0, model


def test_a_public_site_refuses_writes_from_other_sites(client, settings):
    sign_up(client)
    evil = {"Origin": "https://evil.example"}
    assert client.post("/watchlist", json=WATCH, headers=evil).status_code == 403
    same = {"Origin": "http://testserver"}
    assert client.post("/watchlist", json=WATCH, headers=same).status_code == 201


def test_a_frontend_on_another_site_signs_in_with_a_bearer_token(client, settings):
    # The frontend on another site (GitHub Pages in production), the API elsewhere:
    # browsers won't send the cookie. The CORS list is read at import, so this uses one
    # of the default origins.
    pages = settings.allowed_origins[0]
    preflight = client.options(
        "/watchlist",
        headers={
            "Origin": pages,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == pages
    me = sign_up(client)
    client.cookies.clear()
    bearer = {"Authorization": f"Bearer {me['token']}", "Origin": pages}
    assert client.get("/auth/me", headers=bearer).json()["workspace"] == "personal"
    assert client.post("/watchlist", json=WATCH, headers=bearer).status_code == 201
    assert len(client.get("/watchlist", headers=bearer).json()) == 1
    # Another site with the same token is still refused, and signing out ends the token.
    evil = {**bearer, "Origin": "https://evil.example"}
    assert client.post("/watchlist", json=WATCH, headers=evil).status_code == 403
    assert client.post("/auth/logout", headers=bearer).status_code == 204
    assert client.get("/auth/me", headers=bearer).json()["user"] is None


def test_admin_token_still_reaches_the_shared_workspace(client, settings):
    settings.admin_token = "s3cret"
    bearer = {"Authorization": "Bearer s3cret"}
    assert client.post("/watchlist", json=WATCH, headers=bearer).status_code == 201
    assert len(client.get("/watchlist", headers=bearer).json()) == 1
    sign_up(client)
    assert client.get("/watchlist").json() == []
    # A signed-in person still can't upload data; that stays with the token.
    files = {"file": ("ucdp.csv", b"id\n", "text/csv")}
    assert client.post("/ingest/ucdp", files=files).status_code == 401


def test_the_site_serves_the_api_and_frontend_from_one_origin(
    client, settings, tmp_path, monkeypatch
):
    import importlib

    from fastapi.testclient import TestClient

    import app.site

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Conflict Map</title>")
    (tmp_path / "assets" / "app-1a2b.js").write_text("console.log(1)")
    monkeypatch.setattr(settings, "static_dir", str(tmp_path))
    monkeypatch.setattr(settings, "public_mode", False)
    site = importlib.reload(app.site).app
    with TestClient(site) as browser:
        page = browser.get("/")
        assert "Conflict Map" in page.text and page.headers["cache-control"] == "no-cache"
        asset = browser.get("/assets/app-1a2b.js")
        assert "immutable" in asset.headers["cache-control"]
        assert browser.get("/api/health").json() == {"status": "ok"}
        # The sign-in cookie set under /api is sent back for the whole site.
        signed = browser.post("/api/auth/signup", json={"email": "a@b.org", "password": PASSWORD})
        assert signed.status_code == 201
        assert browser.post("/api/watchlist", json=WATCH).status_code == 201
        assert browser.get("/api/auth/me").json()["workspace"] == "personal"
