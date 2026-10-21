"""Link boards, end to end on a small synthetic world.

The world is in Mali: a town named Testville (another Testville is in Niger), Riverbend
140 km away, and Paris, which the article mentions in passing. The events are synthetic
rows in each source's style; nothing here is real reporting.
"""

import base64
import hashlib
import json
from datetime import UTC, date, datetime

import pytest

from app.boards import export
from app.boards.extract import (
    ClaudeExtractor,
    ExtractedActor,
    ExtractedClaim,
    ExtractedPlace,
    Extraction,
    ExtractionError,
)
from app.boards.models import Observation
from app.config import get_settings
from app.models import Event, EventLink, IngestRun

ARTICLE_URL = "https://news.example/2026/10/16/malian-forces-battle-jnim-near-testville"
ANCHOR = date(2026, 10, 16)
ARTICLE = {
    "url": ARTICLE_URL,
    "title": "Malian forces battle JNIM near Testville",
    "published": ANCHOR.isoformat(),
    "extractor": "gazetteer",
    "text": (
        "TESTVILLE, Mali — Malian troops clashed with JNIM fighters near Testville on "
        "Sunday, officials said. The army said the fighting spread toward Riverbend.\n\n"
        "In Paris, France's foreign ministry condemned the violence. Mali has faced an "
        "insurgency since 2012. Residents of Testville fled toward Riverbend, and Mali's "
        "government promised help."
    ),
}
TESTVILLE = (14.50, -4.20)
RIVERBEND = (15.00, -3.00)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No network in tests: no geocoder, no elevation service, no Claude."""
    settings = get_settings()
    monkeypatch.setattr(settings, "board_geocoder", "none")
    monkeypatch.setattr(settings, "board_elevation", "none")
    monkeypatch.setattr(settings, "board_extractor", "gazetteer")


def add_event(session, run, key, **fields):
    defaults = dict(
        source="acled",
        source_event_id=key,
        dedupe_key=key,
        event_type="battle",
        is_violent=True,
        country="Mali",
        country_iso3="MLI",
        geo_precision="exact",
        report_count=1,
        attributes={},
        ingest_run_id=run.id,
    )
    defaults.update(fields)
    event = Event(**defaults)
    session.add(event)
    session.flush()
    return event


@pytest.fixture
def world(session):
    run = IngestRun(source="test", filename="synthetic", status="done")
    session.add(run)
    session.flush()
    e = {}
    e["history"] = add_event(
        session,
        run,
        "u-hist",
        source="ucdp",
        event_type="state_based",
        event_date=date(2024, 5, 1),
        location_name="Testville town",
        latitude=TESTVILLE[0],
        longitude=TESTVILLE[1],
        fatalities_best=25,
        actor1="Government of Mali",
        actor2="JNIM: Group for Support of Islam and Muslims",
    )
    e["battle"] = add_event(
        session,
        run,
        "a-battle",
        event_date=date(2026, 10, 11),
        location_name="Testville",
        latitude=TESTVILLE[0] + 0.01,
        longitude=TESTVILLE[1],
        fatalities_best=4,
        actor1="Military Forces of Mali (2021-)",
        actor2="JNIM: Group for Support of Islam and Muslims",
        attributes={"notes": "On 11 October 2026, the army clashed with JNIM near Testville."},
    )
    e["battle_ucdp"] = add_event(
        session,
        run,
        "u-battle",
        source="ucdp",
        event_type="state_based",
        event_date=date(2026, 10, 11),
        location_name="Testville town",
        latitude=TESTVILLE[0] + 0.03,
        longitude=TESTVILLE[1],
        fatalities_best=5,
        actor1="Government of Mali",
        actor2="JNIM: Group for Support of Islam and Muslims",
    )
    session.add(
        EventLink(
            event_id=e["battle"].id,
            related_event_id=e["battle_ucdp"].id,
            link_type="possible_duplicate",
            distance_km=3.3,
            day_gap=0,
            score=0.8,
        )
    )
    e["coded_a"] = add_event(
        session,
        run,
        "g-1",
        source="gdelt",
        event_type="fight",
        event_date=date(2026, 10, 15),
        location_name="Testville, Mopti, Mali",
        latitude=TESTVILLE[0],
        longitude=TESTVILLE[1],
        actor1="MALI",
        source_url=ARTICLE_URL,
        report_count=12,
        attributes={"actor1_code": "MLIMIL"},
    )
    e["coded_b"] = add_event(
        session,
        run,
        "g-2",
        source="gdelt",
        event_type="assault",
        event_date=date(2026, 10, 15),
        location_name="Testville, Mopti, Mali",
        latitude=TESTVILLE[0] + 0.002,
        longitude=TESTVILLE[1],
        source_url=ARTICLE_URL,
        report_count=3,
    )
    e["threat"] = add_event(
        session,
        run,
        "g-3",
        source="gdelt",
        event_type="threat",
        is_violent=False,
        event_date=date(2026, 10, 15),
        location_name="Testville, Mopti, Mali",
        latitude=TESTVILLE[0],
        longitude=TESTVILLE[1],
        report_count=50,
    )
    e["riverbend"] = add_event(
        session,
        run,
        "a-river",
        event_date=date(2026, 10, 1),
        location_name="Riverbend",
        latitude=RIVERBEND[0],
        longitude=RIVERBEND[1],
        fatalities_best=2,
        actor1="JNIM: Group for Support of Islam and Muslims",
        actor2="Civilians (Mali)",
    )
    e["far"] = add_event(
        session,
        run,
        "a-far",
        event_date=date(2026, 10, 10),
        location_name="Bamako",
        latitude=12.65,
        longitude=-8.0,
        actor1="JNIM: Group for Support of Islam and Muslims",
    )
    for i in range(3):
        add_event(
            session,
            run,
            f"u-ner-{i}",
            source="ucdp",
            event_type="state_based",
            event_date=date(2023, 1, 1 + i),
            country="Niger",
            country_iso3="NER",
            location_name="Testville town",
            latitude=13.5,
            longitude=2.1,
        )
    # A real city: GDELT-only names need a handful of events to count as places.
    for i in range(6):
        add_event(
            session,
            run,
            f"g-paris-{i}",
            source="gdelt",
            event_type="fight",
            event_date=date(2026, 10, 14),
            country="France",
            country_iso3="FRA",
            location_name="Paris, Ile-de-France, France",
            latitude=48.85,
            longitude=2.35,
        )
    session.add_all(
        [
            Observation(
                source="adsb.lol",
                kind="flight",
                external_id="ae0001",
                observed_at=datetime(2026, 10, 16, 10, 0, tzinfo=UTC),
                latitude=TESTVILLE[0] + 0.2,
                longitude=TESTVILLE[1],
                label="RCH1 · C17",
                attributes={"type": "C17"},
            ),
            Observation(
                source="adsb.lol",
                kind="flight",
                external_id="ae0001",
                observed_at=datetime(2026, 10, 16, 10, 5, tzinfo=UTC),
                latitude=TESTVILLE[0] + 0.3,
                longitude=TESTVILLE[1] + 0.1,
                label="RCH1 · C17",
                attributes={"type": "C17"},
            ),
            Observation(
                source="firms:viirs_snpp_nrt",
                kind="fire",
                external_id="N:14.5:-4.2",
                observed_at=datetime(2026, 10, 11, 13, 0, tzinfo=UTC),
                latitude=TESTVILLE[0] + 0.02,
                longitude=TESTVILLE[1] - 0.01,
                label="VIIRS N",
                attributes={"frp": "12.5"},
            ),
        ]
    )
    session.commit()
    return e


def draft(client, **overrides):
    response = client.post("/boards/draft", json={**ARTICLE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def by_kind(board, kind):
    return [n for n in board["nodes"] if n["kind"] == kind]


def links_by_rule(board, rule):
    return [k for k in board["links"] if k["rule"] == rule]


def node_for_event(board, event):
    return next((n for n in board["nodes"] if n["event_id"] == event.id), None)


def test_draft_finds_places_actors_and_linked_events(client, world):
    board = draft(client)
    nodes = {n["id"]: n for n in board["nodes"]}
    assert board["extractor"] == "gazetteer"
    assert board["anchor_date"] == ANCHOR.isoformat()

    article = by_kind(board, "article")[0]
    assert article["status"] == "accepted"
    # The dateline puts the article at Testville.
    assert article["latitude"] == pytest.approx(TESTVILLE[0], abs=0.05)
    assert all(n["status"] == "suggested" for n in board["nodes"] if n["kind"] != "article")
    assert all(k["status"] == "suggested" for k in board["links"])

    places = {n["label"]: n for n in by_kind(board, "place")}
    assert set(places) == {"Testville", "Riverbend", "Paris"}
    # The Mali Testville, not the one in Niger, and the board says there was a choice.
    assert places["Testville"]["attributes"]["iso3"] == "MLI"
    mention = next(
        k for k in links_by_rule(board, "mentions") if k["to_node_id"] == places["Testville"]["id"]
    )
    assert mention["confidence"] == 0.6 and "1 other place" in mention["reason"]
    assert mention["evidence"]["quote"]
    paris = next(
        k for k in links_by_rule(board, "mentions") if k["to_node_id"] == places["Paris"]["id"]
    )
    assert paris["confidence"] == 0.5 and "outside the story's main countries" in paris["reason"]

    actors = {n["label"]: n for n in by_kind(board, "actor")}
    assert "Malian state forces" in actors
    assert "JNIM: Group for Support of Islam and Muslims" in actors
    assert (
        "Military Forces of Mali (2021-)" in actors["Malian state forces"]["attributes"]["db_names"]
    )

    # GDELT coded two events from this very article; they share its report.
    coded = {nodes[k["to_node_id"]]["event_id"] for k in links_by_rule(board, "coded_from")}
    assert coded == {world["coded_a"].id, world["coded_b"].id}
    assert len(links_by_rule(board, "co_reported")) == 1

    # Recent events near Testville, with distances and days in the reason.
    battle = node_for_event(board, world["battle"])
    near = [k for k in links_by_rule(board, "near") if k["to_node_id"] == battle["id"]]
    assert near and "5 days before" in near[0]["reason"]
    assert 0.2 <= near[0]["confidence"] <= 0.9
    # Two sources, one incident.
    assert links_by_rule(board, "same_incident")
    # History: the deadly 2024 UCDP event, as background with lower confidence.
    history = node_for_event(board, world["history"])
    assert history["attributes"]["history"] is True
    hist_link = next(k for k in links_by_rule(board, "history") if k["to_node_id"] == history["id"])
    assert hist_link["confidence"] < 0.6 and "25 reported deaths" in hist_link["reason"]

    # Same actor: JNIM at Riverbend (in the region) but not in Bamako (too far).
    jnim = actors["JNIM: Group for Support of Islam and Muslims"]
    jnim_events = {
        nodes[k["to_node_id"]]["event_id"]
        for k in links_by_rule(board, "same_actor")
        if k["from_node_id"] == jnim["id"]
    }
    assert world["riverbend"].id in jnim_events
    assert world["far"].id not in jnim_events
    # Malian forces match GDELT's MLIMIL code.
    mali = actors["Malian state forces"]
    codes = [
        k
        for k in links_by_rule(board, "same_actor")
        if k["from_node_id"] == mali["id"] and k["evidence"].get("gdelt_code") == "MLIMIL"
    ]
    assert codes

    # Left out: GDELT's non-violent codes, and events around passing mentions (Paris).
    assert node_for_event(board, world["threat"]) is None
    assert not [
        n
        for n in board["nodes"]
        if n["kind"] == "event" and n["attributes"].get("country") == "France"
    ]

    # Recorded observations: the flight near Testville, the fire at the battle.
    flight = by_kind(board, "flight")[0]
    assert flight["geometry"]["type"] == "LineString"
    fire = by_kind(board, "fire")[0]
    assert any(
        k["from_node_id"] == battle["id"] and k["to_node_id"] == fire["id"]
        for k in links_by_rule(board, "near")
    )

    # Every link explains itself.
    assert all(k["reason"] and 0 <= k["confidence"] <= 1 for k in board["links"])


def test_draft_needs_an_article(client):
    response = client.post("/boards/draft", json={"title": "nothing"})
    assert response.status_code == 422


def test_draft_refuses_private_urls(client):
    response = client.post("/boards/draft", json={"url": "http://127.0.0.1:8000/boards"})
    assert response.status_code == 422
    assert "public" in response.json()["detail"]


def test_review_accept_reject_and_cascade(client, world):
    board = draft(client)
    bid = board["id"]
    places = {n["label"]: n for n in by_kind(board, "place")}
    paris = places["Paris"]

    # Rejecting a node rejects its links.
    response = client.patch(f"/boards/{bid}/nodes/{paris['id']}", json={"status": "rejected"})
    assert response.status_code == 200
    after = client.get(f"/boards/{bid}").json()
    assert all(
        k["status"] == "rejected"
        for k in after["links"]
        if paris["id"] in (k["from_node_id"], k["to_node_id"])
    )

    # Accepting a link accepts both its ends.
    link = links_by_rule(after, "history")[0]
    client.patch(f"/boards/{bid}/links/{link['id']}", json={"status": "accepted"})
    after = client.get(f"/boards/{bid}").json()
    ends = [n for n in after["nodes"] if n["id"] in (link["from_node_id"], link["to_node_id"])]
    assert all(n["status"] == "accepted" for n in ends)

    # Bulk review.
    ids = [k["id"] for k in links_by_rule(after, "near")]
    after = client.post(
        f"/boards/{bid}/review", json={"status": "accepted", "link_ids": ids}
    ).json()
    assert all(k["status"] == "accepted" for k in after["links"] if k["id"] in ids)

    listing = client.get("/boards").json()
    assert listing[0]["id"] == bid and listing[0]["accepted"] > 1


def test_manual_nodes_links_and_expand(client, world):
    board = client.post("/boards", json={"title": "By hand", "anchor_date": "2026-10-16"}).json()
    bid = board["id"]
    event = client.post(f"/boards/{bid}/nodes", json={"event_id": world["battle"].id}).json()
    assert event["status"] == "accepted" and event["created_by"] == "user"
    note = client.post(
        f"/boards/{bid}/nodes",
        json={
            "label": "Checkpoint seen in video",
            "latitude": 14.52,
            "longitude": -4.21,
            "time_start": "2026-10-12T09:00:00Z",
        },
    ).json()
    link = client.post(
        f"/boards/{bid}/links",
        json={
            "from_node_id": note["id"],
            "to_node_id": event["id"],
            "reason": "Same road",
        },
    )
    assert link.status_code == 201 and link.json()["confidence"] == 1.0
    duplicate = client.post(
        f"/boards/{bid}/links",
        json={
            "from_node_id": event["id"],
            "to_node_id": note["id"],
            "reason": "again",
        },
    )
    assert duplicate.status_code == 409

    expanded = client.post(f"/boards/{bid}/nodes/{event['id']}/expand").json()
    event_ids = {n["event_id"] for n in expanded["nodes"]}
    # The other source's report of the same incident, and the battle's actors.
    assert world["battle_ucdp"].id in event_ids
    assert {"Military Forces of Mali (2021-)", "JNIM: Group for Support of Islam and Muslims"} <= {
        n["label"] for n in by_kind(expanded, "actor")
    }
    assert links_by_rule(expanded, "same_incident")
    # Expanding again adds nothing new.
    again = client.post(f"/boards/{bid}/nodes/{event['id']}/expand").json()
    assert len(again["nodes"]) == len(expanded["nodes"])


def test_geojson_for_the_map(client, world):
    board = draft(client)
    data = client.get(f"/boards/{board['id']}/geojson?include=all").json()
    assert data["type"] == "FeatureCollection"
    kinds = {f["properties"].get("kind") for f in data["features"]}
    assert {"article", "place", "event"} <= kinds
    battle = next(
        f
        for f in data["features"]
        if f["properties"].get("node_id") == node_for_event(board, world["battle"])["id"]
    )
    assert battle["properties"]["day"] == (date(2026, 10, 11) - date(1970, 1, 1)).days
    links = [f for f in data["features"] if "link_id" in f["properties"]]
    assert links and all(len(f["geometry"]["coordinates"]) == 2 for f in links)


def test_bundle_matches_the_globe_format(client, world):
    board = draft(client)
    bid = board["id"]
    # Nothing accepted yet beyond the article: the accepted-only export is the article.
    response = client.get(f"/boards/{bid}/bundle?include=all")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    data = response.json()
    assert data["format"] == "gev-scene-bundle" and data["version"] == 1
    project = data["project"]
    assert project["version"] == 6
    scene = project["scenes"][0]
    assert len(scene["dataPacks"]) <= 8
    assets = {a["path"]: a for a in data["assets"]}
    pack_features = {}
    for pack in scene["dataPacks"]:
        asset = assets[pack["source"]["path"]]
        raw = base64.b64decode(asset["base64"])
        assert hashlib.sha256(raw).hexdigest() == asset["sha256"] == pack["sha256"]
        assert pack["byteLength"] == len(raw)
        geo = json.loads(raw)
        ids = [f["id"] for f in geo["features"]]
        assert len(ids) == len(set(ids)) and all(isinstance(i, str) for i in ids)
        for f in geo["features"]:
            coords = f["geometry"]["coordinates"]
            points = [coords] if f["geometry"]["type"] == "Point" else coords
            assert all(len(p) == 3 for p in points), "heights must be explicit"
        pack_features[pack["id"]] = set(ids)
    titles = [s["title"] for s in scene["shots"]]
    assert titles[0] == "The story" and "How we got here" in titles
    for shot in scene["shots"]:
        assert len(shot["interactions"]) <= 64
        for card in shot["interactions"]:
            assert card["target"]["packId"] in shot["dataPackIds"]
            assert card["target"]["featureId"] in pack_features[card["target"]["packId"]]
            assert len(card["action"]["text"]) <= 4096
            url = card["action"].get("url")
            assert url is None or ("?" not in url and url.startswith("https://"))
    # Only a final "now" shot may switch on the globe's live layers.
    assert all("layers" not in s for s in scene["shots"][:-1])


def test_accepted_only_export_and_empty_board(client, world):
    empty = client.post("/boards", json={"title": "Empty"}).json()
    assert client.get(f"/boards/{empty['id']}/bundle").status_code == 409
    board = draft(client)
    accepted = client.get(f"/boards/{board['id']}/bundle").json()
    packs = accepted["project"]["scenes"][0]["dataPacks"]
    features = sum(
        len(json.loads(base64.b64decode(a["base64"]))["features"]) for a in accepted["assets"]
    )
    assert len(packs) == 1 and features == 1  # only the article


def test_live_scene_and_packs(client, world):
    board = draft(client)
    bid = board["id"]
    scene = client.get(f"/boards/{bid}/scene.json?include=all").json()
    packs = scene["scenes"][0]["dataPacks"]
    assert all(p["source"]["adapter"] == "conflict-map" for p in packs)
    assert all("sha256" not in p for p in packs)
    path = packs[0]["source"]["path"]
    assert "?" not in path
    response = client.get(f"/scene-packs/{path}", headers={"Origin": "http://localhost:4173"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")
    assert response.headers["access-control-allow-origin"] == "http://localhost:4173"
    assert client.get(f"/scene-packs/boards/{bid}/all/99.geojson").status_code == 404


def test_recent_story_gets_a_live_shot(session, world):
    from app.boards.models import Board, BoardNode

    board = Board(
        id=999,
        title="Live",
        origin="manual",
        anchor_date=date(2026, 10, 16),
        created_at=datetime(2026, 10, 16, tzinfo=UTC),
    )
    board.nodes = [
        BoardNode(
            id=1,
            key="article",
            kind="article",
            label="A",
            detail="",
            latitude=14.5,
            longitude=-4.2,
            status="accepted",
            created_by="user",
            attributes={},
            time_start=datetime(2026, 10, 16, tzinfo=UTC),
        )
    ]
    board.links = []
    project, _ = export.build_scene(board, now=datetime(2026, 10, 20, tzinfo=UTC))
    last = project["scenes"][0]["shots"][-1]
    assert last["id"] == "shot-now"
    assert set(last["layers"]) == set(export.LIVE_LAYERS)


class FakeClaude:
    """Stands in for anthropic.Anthropic; returns a canned parsed extraction."""

    def __init__(self, extraction=None, stop_reason="end_turn", error=None):
        self.extraction, self.stop_reason, self.error = extraction, stop_reason, error
        self.beta = self
        self.messages = self
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error

        class Usage:
            input_tokens, output_tokens = 1000, 200

        class Response:
            parsed_output = self.extraction
            stop_reason = self.stop_reason
            model = "claude-opus-5-5"
            _request_id = "req_test"
            usage = Usage()

        return Response()


def claude_extraction():
    return Extraction(
        title="Malian forces battle JNIM near Testville",
        published="2026-10-16",
        countries=["Mali", "France"],
        focus_countries=["Mali"],
        places=[
            ExtractedPlace(
                name="Testville",
                country="Mali",
                quote="Malian troops clashed with JNIM fighters near Testville on "
                "Sunday, officials said.",
            ),
            ExtractedPlace(name="Riverbend", country="Mali", quote="invented quote"),
        ],
        actors=[
            ExtractedActor(name="Malian troops", kind="state_force", country="Mali", quote=None)
        ],
        claims=[
            ExtractedClaim(
                summary="Malian troops clashed with JNIM near Testville",
                date="2026-10-11",
                place="Testville",
                actors=["Malian troops", "JNIM"],
                quote="Malian troops clashed with JNIM fighters near Testville on "
                "Sunday, officials said.",
            ),
            ExtractedClaim(
                summary="Made-up claim",
                date=None,
                place="Riverbend",
                actors=[],
                quote="This sentence is not in the article.",
            ),
        ],
    )


def test_claude_extraction_is_checked_against_the_article(session, world):
    from app.boards.articles import Article

    fake = FakeClaude(claude_extraction())
    article = Article(text=ARTICLE["text"], title=ARTICLE["title"], url=ARTICLE_URL)
    result = ClaudeExtractor(client=fake).extract(session, article, ANCHOR)
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is Extraction
    assert call["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in call["betas"]
    # Quotes that are not in the article are dropped; claims without one are dropped.
    assert result.places[0].quote and result.places[1].quote is None
    assert [c.summary for c in result.claims] == ["Malian troops clashed with JNIM near Testville"]


def test_claude_refusal_and_errors(session):
    from app.boards.articles import Article

    article = Article(text="x" * 300)
    with pytest.raises(ExtractionError, match="declined"):
        ClaudeExtractor(client=FakeClaude(stop_reason="refusal")).extract(session, article, ANCHOR)
    with pytest.raises(ExtractionError, match="cut off"):
        ClaudeExtractor(client=FakeClaude(None, stop_reason="max_tokens")).extract(
            session, article, ANCHOR
        )


def test_claude_board_has_claims_linked_to_matching_events(client, world, monkeypatch):
    from app.boards import extract

    monkeypatch.setattr(
        extract,
        "get_extractor",
        lambda kind=None: ClaudeExtractor(client=FakeClaude(claude_extraction())),
    )
    import app.api.boards as api

    monkeypatch.setattr(api, "get_extractor", extract.get_extractor)
    board = draft(client, extractor="claude")
    assert board["extractor"] == "claude"
    claim = by_kind(board, "claim")[0]
    assert claim["created_by"] == "ai" and claim["quote"]
    assert claim["time_start"].startswith("2026-10-11")
    # The ACLED battle on the same day, 1 km away, may be the incident the article reports.
    battle = node_for_event(board, world["battle"])
    match = [
        k
        for k in board["links"]
        if k["from_node_id"] == claim["id"] and k["to_node_id"] == battle["id"]
    ]
    assert match and match[0]["reason"].startswith("possibly the same incident")
    actor = by_kind(board, "actor")[0]
    assert actor["label"] == "Malian troops"
    assert "Military Forces of Mali (2021-)" in actor["attributes"]["db_names"]


def test_claude_failure_falls_back_to_the_gazetteer(client, world, monkeypatch):
    import app.api.boards as api

    failing = ClaudeExtractor(client=FakeClaude(error=ExtractionError("boom")))
    failing.extract = lambda *a, **k: (_ for _ in ()).throw(ExtractionError("rate limited"))
    monkeypatch.setattr(api, "get_extractor", lambda kind=None: failing)
    board = draft(client, extractor="auto")
    assert board["extractor"] == "gazetteer"
    assert "Claude extraction failed (rate limited)" in board["notes"]
    # Asked for Claude explicitly, the failure is an error instead.
    response = client.post("/boards/draft", json={**ARTICLE, "extractor": "claude"})
    assert response.status_code == 502


def test_topic_board_merges_articles(client, world, monkeypatch):
    from app.boards import topic
    from app.boards.articles import Article

    found = [
        topic.Found(url=ARTICLE_URL, title=ARTICLE["title"], seen=ANCHOR, domain="news.example"),
        topic.Found(
            url="https://other.example/riverbend",
            title="Riverbend residents flee",
            seen=date(2026, 10, 15),
            domain="other.example",
        ),
    ]
    monkeypatch.setattr(topic, "search_articles", lambda *a, **k: found)
    texts = {
        ARTICLE_URL: ARTICLE["text"],
        "https://other.example/riverbend": (
            "RIVERBEND, Mali — Residents fled Riverbend after JNIM fighters attacked the "
            "market, Malian officials said. The army sent troops from Testville."
        ),
    }

    def fake_fetch(url):
        return Article(text=texts[url], url=url, published=None)

    monkeypatch.setattr(topic, "fetch_article", fake_fetch)
    response = client.post(
        "/boards/topic", json={"topic": "JNIM in Mali", "extractor": "gazetteer"}
    )
    assert response.status_code == 201, response.text
    board = response.json()
    assert board["origin"] == "topic"
    assert len(by_kind(board, "article")) == 2
    # Riverbend is named by both articles: one node, two mentions.
    riverbend = [n for n in by_kind(board, "place") if n["label"] == "Riverbend"]
    assert len(riverbend) == 1
    mentions = [
        k for k in links_by_rule(board, "mentions") if k["to_node_id"] == riverbend[0]["id"]
    ]
    assert len(mentions) == 2


def test_topic_with_no_coverage(client, monkeypatch):
    from app.boards import topic

    monkeypatch.setattr(topic, "search_articles", lambda *a, **k: [])
    response = client.post("/boards/topic", json={"topic": "nothing at all"})
    assert response.status_code == 404


def test_topic_search_retries_when_gdelt_is_busy(monkeypatch):
    import io
    import urllib.error

    from app.boards import topic

    answers = [
        urllib.error.HTTPError("u", 429, "Too Many Requests", {}, io.BytesIO(b"")),
        io.BytesIO(
            json.dumps(
                {
                    "articles": [
                        {
                            "url": "https://a.example/1",
                            "title": "Clashes in Testville",
                            "seendate": "20261016T120000Z",
                            "domain": "a.example",
                        },
                        {
                            "url": "https://b.example/1",
                            "title": "Clashes in  Testville",
                            "seendate": "20261016T130000Z",
                            "domain": "b.example",
                        },
                    ]
                }
            ).encode()
        ),
    ]

    class Opened:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self.body

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Opened(answer)

    monkeypatch.setattr(topic.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(topic.time, "sleep", lambda seconds: None)
    found = topic.search_articles("Testville")
    # The same wire story on two sites counts once.
    assert [f.url for f in found] == ["https://a.example/1"]
    assert found[0].seen == date(2026, 10, 16)


def test_gdelt_query_quotes_short_words():
    from app.boards.topic import gdelt_query

    assert gdelt_query("El Fasher") == '"El Fasher"'
    assert gdelt_query("Wagner  Mali") == "Wagner Mali"
    assert gdelt_query('"Rapid Support Forces" Darfur') == '"Rapid Support Forces" Darfur'


def test_topic_falls_back_to_its_own_words(client, world, monkeypatch):
    from app.boards import topic

    def down(*args, **kwargs):
        raise topic.TopicError("GDELT article search failed: HTTP Error 429")

    monkeypatch.setattr(topic, "search_articles", down)
    response = client.post("/boards/topic", json={"topic": "JNIM in Testville, Mali", "days": 30})
    assert response.status_code == 201, response.text
    board = response.json()
    assert "429" in board["notes"] and "topic's words" in board["notes"]
    assert {n["label"] for n in by_kind(board, "place")} == {"Testville"}
    assert by_kind(board, "event")


def test_expanding_a_group_reaches_its_older_record(client, world):
    board = draft(client)
    jnim = next(n for n in by_kind(board, "actor") if n["label"].startswith("JNIM"))
    expanded = client.post(f"/boards/{board['id']}/nodes/{jnim['id']}/expand").json()
    linked = {
        n["event_id"]
        for k in links_by_rule(expanded, "same_actor")
        if k["from_node_id"] == jnim["id"]
        for n in expanded["nodes"]
        if n["id"] == k["to_node_id"]
    }
    # The 2024 UCDP event is outside the 60-day lookback but in the group's record.
    assert world["history"].id in linked
