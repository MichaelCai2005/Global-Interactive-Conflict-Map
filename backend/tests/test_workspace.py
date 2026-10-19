from tests.test_ingest import load_sample


def test_watchlist_lifecycle(client):
    created = client.post("/watchlist", json={"name": "Donbas", "bbox": "36,47,40,50"})
    assert created.status_code == 201
    item = created.json()
    assert (item["name"], item["country"], item["notes"]) == ("Donbas", None, "")

    client.post("/watchlist", json={"name": "Sudan", "country": "Sudan"})
    assert [w["name"] for w in client.get("/watchlist").json()] == ["Donbas", "Sudan"]

    patched = client.patch(f"/watchlist/{item['id']}", json={"notes": "front line"}).json()
    assert (patched["name"], patched["notes"]) == ("Donbas", "front line")

    assert client.delete(f"/watchlist/{item['id']}").status_code == 204
    assert [w["name"] for w in client.get("/watchlist").json()] == ["Sudan"]
    assert client.delete(f"/watchlist/{item['id']}").status_code == 404


def test_watch_items_need_a_place(client):
    assert client.post("/watchlist", json={"name": "Nowhere"}).status_code == 422
    assert client.post("/watchlist", json={"name": "Bad", "bbox": "40,47,36,50"}).status_code == 422
    assert client.post("/watchlist", json={"name": "", "country": "Sudan"}).status_code == 422


def test_tasks_link_to_events_and_filter_by_status(client, session, tmp_path):
    load_sample(session, tmp_path)
    event = client.get("/events", params={"source": "ucdp", "bbox": "36,49,37,51"}).json()["items"][
        0
    ]

    created = client.post(
        "/tasks", json={"title": "Check casualty figures", "event_id": event["id"]}
    ).json()
    assert (created["status"], created["priority"]) == ("open", "normal")
    assert created["event"]["id"] == event["id"]
    assert created["event"]["event_date"] == event["event_date"]

    other = client.post("/tasks", json={"title": "Weekly summary", "priority": "high"}).json()
    assert other["event"] is None

    done = client.patch(f"/tasks/{other['id']}", json={"status": "done"}).json()
    assert done["status"] == "done"
    assert done["updated_at"] >= other["updated_at"]

    open_titles = [t["title"] for t in client.get("/tasks", params={"status": "open"}).json()]
    assert open_titles == ["Check casualty figures"]
    for_event = client.get("/tasks", params={"event_id": event["id"]}).json()
    assert [t["id"] for t in for_event] == [created["id"]]

    assert client.delete(f"/tasks/{created['id']}").status_code == 204
    assert [t["id"] for t in client.get("/tasks").json()] == [other["id"]]


def test_task_validation(client):
    assert client.post("/tasks", json={"title": "x", "event_id": 999}).status_code == 404
    assert client.post("/tasks", json={"title": "x", "watch_item_id": 999}).status_code == 404
    assert client.post("/tasks", json={"title": "x", "status": "maybe"}).status_code == 422
    assert client.patch("/tasks/999", json={"status": "done"}).status_code == 404
