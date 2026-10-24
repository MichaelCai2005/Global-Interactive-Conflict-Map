"""Boards as mood boards: cards without a map place, canvas positions, pictures, your own
links and cards, and articles added to an open board."""

import pytest

from app.config import get_settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "board_geocoder", "none")
    monkeypatch.setattr(settings, "board_elevation", "none")
    monkeypatch.setattr(settings, "board_extractor", "gazetteer")


@pytest.fixture
def board(client):
    response = client.post("/boards", json={"title": "Mood board", "anchor_date": "2026-10-16"})
    assert response.status_code == 201
    return response.json()


def add(client, board, **fields):
    response = client.post(f"/boards/{board['id']}/nodes", json=fields)
    assert response.status_code == 201, response.text
    return response.json()


def test_cards_need_no_map_place(client, board):
    idea = add(client, board, label="Who supplies the drones?", detail="Check the shipping records")
    link = add(
        client,
        board,
        kind="link",
        label="UN panel report",
        source_url="https://un.example/report",
        board_x=120,
        board_y=-40,
    )
    assert idea["latitude"] is None and idea["status"] == "accepted"
    assert (link["board_x"], link["board_y"]) == (120, -40)
    # Off-map cards stay off the map.
    features = client.get(f"/boards/{board['id']}/geojson").json()["features"]
    assert features == []


@pytest.mark.parametrize(
    "fields",
    [
        {"label": "x", "source_url": "javascript:alert(1)"},
        {"label": "x", "image_url": "data:image/png;base64,AAAA"},
        {"label": "x", "image_url": "/boards/images/1/../2"},
        {"label": "x", "latitude": 10},
        {"label": "x", "board_x": 10},
        {"label": "   "},
        {"kind": "event", "label": "x"},
    ],
)
def test_bad_cards_are_refused(client, board, fields):
    assert client.post(f"/boards/{board['id']}/nodes", json=fields).status_code == 422


def test_edit_a_card_and_clear_its_parts(client, board):
    card = add(client, board, label="Note", image_url="https://img.example/a.jpg")
    url = f"/boards/{board['id']}/nodes/{card['id']}"
    done = client.patch(
        url, json={"latitude": 14.5, "longitude": -4.2, "detail": "Seen here"}
    ).json()
    assert (done["latitude"], done["geo_basis"], done["detail"]) == (14.5, "user", "Seen here")
    done = client.patch(url, json={"image_url": None, "latitude": None, "longitude": None}).json()
    assert done["image_url"] is None and done["latitude"] is None and done["geo_basis"] is None
    assert client.patch(url, json={"latitude": 1}).status_code == 422
    assert client.patch(url, json={"label": None}).status_code == 422


def test_layout_saves_positions_without_touching_the_board(client, board):
    a = add(client, board, label="A")
    b = add(client, board, label="B")
    before = client.get(f"/boards/{board['id']}").json()["updated_at"]
    response = client.post(
        f"/boards/{board['id']}/layout",
        json={
            "positions": [{"id": a["id"], "x": 10.04, "y": 20}, {"id": b["id"], "x": -5, "y": 0}]
        },
    )
    assert response.json() == {"saved": 2}
    after = client.get(f"/boards/{board['id']}").json()
    assert after["updated_at"] == before
    assert {(n["board_x"], n["board_y"]) for n in after["nodes"]} == {(10.0, 20), (-5, 0)}
    bad = client.post(
        f"/boards/{board['id']}/layout", json={"positions": [{"id": 999, "x": 0, "y": 0}]}
    )
    assert bad.status_code == 422


def test_draw_relabel_and_delete_your_own_lines(client, board):
    a = add(client, board, label="A")
    b = add(client, board, label="B")
    link = client.post(
        f"/boards/{board['id']}/links", json={"from_node_id": a["id"], "to_node_id": b["id"]}
    ).json()
    assert link["reason"] == "" and link["status"] == "accepted"
    url = f"/boards/{board['id']}/links/{link['id']}"
    assert client.patch(url, json={"reason": " same supplier "}).json()["reason"] == "same supplier"
    assert client.delete(url).status_code == 204
    assert client.get(f"/boards/{board['id']}").json()["links"] == []


def test_delete_a_card_takes_its_lines_and_picture(client, board):
    upload = client.post(
        f"/boards/{board['id']}/images", files={"file": ("p.png", PNG, "image/png")}
    ).json()
    a = add(client, board, label="Photo", image_url=upload["url"])
    b = add(client, board, label="B")
    client.post(
        f"/boards/{board['id']}/links", json={"from_node_id": a["id"], "to_node_id": b["id"]}
    )
    assert client.delete(f"/boards/{board['id']}/nodes/{a['id']}").status_code == 204
    left = client.get(f"/boards/{board['id']}").json()
    assert [n["label"] for n in left["nodes"]] == ["B"] and left["links"] == []
    assert client.get(upload["url"]).status_code == 404


def test_pictures_upload_and_serve(client, board):
    response = client.post(
        f"/boards/{board['id']}/images", files={"file": ("photo.png", PNG, "image/png")}
    )
    assert response.status_code == 201
    image = response.json()
    assert image["url"] == f"/boards/images/{image['id']}" and image["content_type"] == "image/png"
    served = client.get(image["url"])
    assert served.content == PNG and served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "data, status",
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", 415),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", 415),
        (b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024), 413),
    ],
    ids=["svg", "wav", "too-big"],
)
def test_only_small_raster_pictures(client, board, data, status):
    response = client.post(
        f"/boards/{board['id']}/images", files={"file": ("x.png", data, "image/png")}
    )
    assert response.status_code == status


def test_add_an_article_to_an_open_board(client, board):
    article = {
        "url": "https://news.example/a",
        "title": "Fighting near Testville",
        "text": "Malian troops clashed near Testville on Sunday, officials said. " * 3,
        "extractor": "gazetteer",
        "board_x": 300,
        "board_y": 50,
    }
    response = client.post(f"/boards/{board['id']}/articles", json=article)
    assert response.status_code == 201, response.text
    nodes = response.json()["nodes"]
    added = next(n for n in nodes if n["kind"] == "article")
    assert added["label"] == "Fighting near Testville"
    assert (added["board_x"], added["board_y"]) == (300, 50)
    again = client.post(
        f"/boards/{board['id']}/articles", json={**article, "url": "https://www.news.example/a/"}
    )
    assert again.status_code == 409


def test_suggestions_are_rejected_not_deleted(client, board):
    article = {"url": "https://news.example/b", "title": "T", "text": "Some text. " * 30}
    nodes = client.post(f"/boards/{board['id']}/articles", json=article).json()["nodes"]
    article_node = next(n for n in nodes if n["kind"] == "article")
    assert client.delete(f"/boards/{board['id']}/nodes/{article_node['id']}").status_code == 409
