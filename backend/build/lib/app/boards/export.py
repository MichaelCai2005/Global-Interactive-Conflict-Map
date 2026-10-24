"""Turn a board into a gods-eye-view scene: a briefing that plays through time.

The scene is a version-6 Director document (gods-eye-view docs/SCENE-DOCUMENT.md):

- Each time step is one GeoJSON data pack: the nodes that appear in it, and the links
  that become complete in it (a link appears once both its ends exist).
- Each shot selects the packs up to its step, so the board grows as the briefing plays.
- Clicking a point or line opens a card with what it is, why it is on the board and a
  source link.

The globe keeps limits, which this module respects and tests check: 8 packs a scene,
2,000 features and 50,000 positions a pack, 64 cards a shot, 4,096 characters a card,
and source links without query strings.

Two ways to deliver it:
- `bundle()` embeds the packs, for the globe's IMPORT button. No fork changes needed.
- `scene_document(adapter="conflict-map")` points the packs at this API, for a globe
  that registers it as a source (see docs/gods-eye-view.md).
"""

import base64
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.boards.elevation import ground_heights
from app.boards.models import Board, BoardLink, BoardNode
from app.boards.names import clean_source_url
from app.boards.rules import utc_day

SCENE_VERSION = 6
LIMITS = {
    "packs": 8,
    "features": 2000,
    "positions": 50000,
    "interactions": 64,
    "card_text": 4096,
    "title": 4096,
    "id": 256,
}
MAX_RECENT_STEPS = 5
# Points float this far above the ground so terrain does not swallow them.
POINT_LIFT_M = 80.0
# The globe's own live layers to switch on in the final shot of a recent story.
LIVE_LAYERS = ("military", "gnss-integrity", "local-firms")
LIVE_WINDOW = timedelta(days=14)

# Style names for gods-eye-view's pack renderer. Upstream draws every feature cyan and
# ignores properties; the fork patch in docs/gods-eye-view.md colours by this field.
STYLE_BY_KIND = {
    "article": "article",
    "place": "place",
    "actor": "actor",
    "claim": "claim",
    "flight": "flight",
    "fire": "fire",
    "vessel": "vessel",
    "note": "note",
}


class ExportError(Exception):
    pass


@dataclass
class Step:
    id: str
    title: str
    nodes: list[BoardNode] = field(default_factory=list)
    links: list[BoardLink] = field(default_factory=list)


def visible(board: Board, include: str) -> tuple[list[BoardNode], list[BoardLink]]:
    """Accepted items only, or everything not rejected ('all')."""
    allowed = {"accepted"} if include == "accepted" else {"accepted", "suggested"}
    nodes = [n for n in board.nodes if n.status in allowed and n.latitude is not None]
    ids = {n.id for n in nodes}
    links = [
        k
        for k in board.links
        if k.status in allowed and k.from_node_id in ids and k.to_node_id in ids
    ]
    return nodes, links


def plan_steps(board: Board, nodes: list[BoardNode], links: list[BoardLink]) -> list[Step]:
    """Split the board into time steps: context, history, then the recent story."""
    anchor = board.anchor_date
    recent_from = None
    if anchor is not None:
        recent_from = datetime.combine(anchor, datetime.min.time(), tzinfo=UTC) - timedelta(days=60)
    context = Step("context", "The story")
    history = Step("history", "How we got here")
    timed = []
    for n in nodes:
        if n.time_start is None or n.kind in ("place", "actor", "article"):
            context.nodes.append(n)
        elif n.attributes.get("history") or (recent_from and n.time_start < recent_from):
            history.nodes.append(n)
        else:
            timed.append(n)
    steps = [context] + ([history] if history.nodes else [])
    steps += _recent_steps(timed)
    # Put each link in the step where its later end appears.
    step_of = {n.id: i for i, s in enumerate(steps) for n in s.nodes}
    for k in links:
        steps[max(step_of[k.from_node_id], step_of[k.to_node_id])].links.append(k)
    return [s for s in steps if s.nodes or s.links]


def _recent_steps(nodes: list[BoardNode]) -> list[Step]:
    if not nodes:
        return []
    days = sorted({utc_day(n.time_start) for n in nodes})
    if len(days) <= MAX_RECENT_STEPS:
        groups = [[d] for d in days]
    else:
        # Equal numbers of days per step, keeping each day whole.
        size = math.ceil(len(days) / MAX_RECENT_STEPS)
        groups = [days[i : i + size] for i in range(0, len(days), size)]
    steps = []
    for group in groups:
        first, last = group[0], group[-1]
        title = _day(first) if first == last else f"{_day(first)} to {_day(last)}"
        step = Step(f"step-{first.isoformat()}", title)
        step.nodes = [n for n in nodes if first <= utc_day(n.time_start) <= last]
        steps.append(step)
    return steps


def _day(d) -> str:
    return f"{d.day} {d:%b %Y}"


# --- Geometry -----------------------------------------------------------------------


def _spread(nodes: list[BoardNode]) -> dict[int, tuple[float, float]]:
    """Display positions: items at the same spot fan out in a small ring.

    GDELT puts every report about a city at its centre, so ten events can share one
    point. Cards still give the true coordinates.
    """
    at: dict[tuple[float, float], list[BoardNode]] = defaultdict(list)
    for n in nodes:
        at[(round(n.latitude, 3), round(n.longitude, 3))].append(n)
    shown: dict[int, tuple[float, float]] = {}
    for group in at.values():
        if len(group) == 1:
            shown[group[0].id] = (group[0].latitude, group[0].longitude)
            continue
        radius_km = 0.6 + 0.25 * len(group)
        for i, n in enumerate(sorted(group, key=lambda n: (n.kind, n.id))):
            angle = 2 * math.pi * i / len(group)
            dlat = radius_km / 111.32 * math.cos(angle)
            dlon = (
                radius_km
                / (111.32 * max(0.1, math.cos(math.radians(n.latitude))))
                * math.sin(angle)
            )
            shown[n.id] = (n.latitude + dlat, n.longitude + dlon)
    return shown


def _great_circle(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    v1 = (math.cos(lat1) * math.cos(lon1), math.cos(lat1) * math.sin(lon1), math.sin(lat1))
    v2 = (math.cos(lat2) * math.cos(lon2), math.cos(lat2) * math.sin(lon2), math.sin(lat2))
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(v1, v2, strict=True))))
    omega = math.acos(dot)
    if omega < 1e-9:
        return a
    s1, s2 = math.sin((1 - t) * omega) / math.sin(omega), math.sin(t * omega) / math.sin(omega)
    x, y, z = (s1 * p + s2 * q for p, q in zip(v1, v2, strict=True))
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def arc(
    a: tuple[float, float, float], b: tuple[float, float, float], segments: int = 16
) -> list[list[float]]:
    """A raised great-circle arc from a to b, as [lon, lat, height] positions.

    A straight 3D line between distant points cuts through the Earth; the arc rises with
    distance so links read as connections above the map.
    """
    distance_km = (
        6371
        * 2
        * math.asin(
            min(
                1.0,
                math.sqrt(
                    math.sin(math.radians(b[0] - a[0]) / 2) ** 2
                    + math.cos(math.radians(a[0]))
                    * math.cos(math.radians(b[0]))
                    * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
                ),
            )
        )
    )
    lift = min(max(distance_km * 1000 * 0.12, 250.0), 400_000.0)
    out = []
    for i in range(segments + 1):
        t = i / segments
        lat, lon = _great_circle((a[0], a[1]), (b[0], b[1]), t)
        height = a[2] + (b[2] - a[2]) * t + lift * math.sin(math.pi * t)
        out.append([round(lon, 6), round(lat, 6), round(height, 1)])
    return out


@dataclass
class Geometry:
    positions: dict[int, tuple[float, float, float]]
    real_heights: bool


def geometry(nodes: list[BoardNode]) -> Geometry:
    shown = _spread(nodes)
    order = sorted(shown)
    heights, real = ground_heights([shown[i] for i in order])
    positions = {
        i: (shown[i][0], shown[i][1], h + POINT_LIFT_M) for i, h in zip(order, heights, strict=True)
    }
    return Geometry(positions, real)


# --- Cards --------------------------------------------------------------------------


def node_card(n: BoardNode, reasons: list[str]) -> str:
    when = utc_day(n.time_start).isoformat() if n.time_start else None
    head = " · ".join(x for x in (n.kind.upper(), when, n.source_name) if x)
    parts = [head, n.label]
    if n.detail:
        parts.append(n.detail)
    if n.quote:
        parts.append(f'Quote: "{n.quote}"')
    if reasons:
        parts.append("On the board because:\n" + "\n".join(f"- {r}" for r in reasons[:4]))
    if n.geo_basis in ("derived", "country"):
        parts.append("Position is approximate: placed by the board, not by a source.")
    parts.append(f"Status: {n.status} · added by {n.created_by}")
    if n.source_url and not clean_source_url(n.source_url):
        parts.append(f"Source: {n.source_url}")
    return _fit("\n\n".join(parts))


def link_card(k: BoardLink, nodes: dict[int, BoardNode]) -> str:
    parts = [
        f"LINK · {k.rule.replace('_', ' ')} · confidence {k.confidence:.2f}",
        f"{nodes[k.from_node_id].label}  →  {nodes[k.to_node_id].label}",
        k.reason,
    ]
    quote = (k.evidence or {}).get("quote")
    if quote:
        parts.append(f'Quote: "{quote}"')
    parts.append(f"Status: {k.status} · suggested by {k.created_by}")
    return _fit("\n\n".join(parts))


def _fit(text: str) -> str:
    limit = LIMITS["card_text"]
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- Packs and scene ----------------------------------------------------------------


def _feature_id(item: BoardNode | BoardLink) -> str:
    return f"{'n' if isinstance(item, BoardNode) else 'l'}{item.id}"


def node_style(n: BoardNode) -> str:
    if n.kind == "event":
        prefix = "history" if n.attributes.get("history") else "event"
        return f"{prefix}-{'violent' if n.attributes.get('violent') else 'signal'}"
    return STYLE_BY_KIND.get(n.kind, "note")


def link_style(k: BoardLink) -> str:
    return f"link-{k.status}"


def pack_geojson(step: Step, geo: Geometry) -> bytes:
    features = []
    for n in step.nodes:
        lat, lon, height = geo.positions[n.id]
        geometry_ = {
            "type": "Point",
            "coordinates": [round(lon, 6), round(lat, 6), round(height, 1)],
        }
        track = n.geometry or {}
        if track.get("type") == "LineString" and len(track.get("coordinates", [])) >= 2:
            # A flight or ship track: drawn at a fixed height above the first point's ground.
            geometry_ = {
                "type": "LineString",
                "coordinates": [[c[0], c[1], round(height + 400, 1)] for c in track["coordinates"]],
            }
        features.append(
            {
                "type": "Feature",
                "id": _feature_id(n),
                "geometry": geometry_,
                "properties": {"gevStyle": node_style(n), "label": n.label[:200], "kind": n.kind},
            }
        )
    for k in step.links:
        a, b = geo.positions[k.from_node_id], geo.positions[k.to_node_id]
        features.append(
            {
                "type": "Feature",
                "id": _feature_id(k),
                "geometry": {"type": "LineString", "coordinates": arc(a, b)},
                "properties": {
                    "gevStyle": link_style(k),
                    "rule": k.rule,
                    "confidence": k.confidence,
                },
            }
        )
    if len(features) > LIMITS["features"]:
        raise ExportError(
            f"Step {step.title!r} has {len(features)} features; the globe takes 2,000"
        )
    data = json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
    return data.encode("utf-8")


def _camera(points: list[tuple[float, float]]) -> dict[str, float]:
    """A camera pose that fits these points on screen, from the south, 65 degrees down.

    Cesium's 60-degree field of view spans the wider screen side, so on a landscape screen
    about 0.58 of the slant distance shows either side of centre across and 0.4 up and
    down. The globe's panels cover the screen's edges, so the points are fitted into the
    middle 55% of the view.
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_c, lon_c = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    ns_km = (max(lats) - min(lats)) * 111.32
    ew_km = (max(lons) - min(lons)) * 111.32 * math.cos(math.radians(lat_c))
    slant_km = min(max(ew_km * 1.6, ns_km * 2.3, 40.0), 7000.0)
    pitch = -65.0
    alt_m = slant_km * 1000 * math.sin(math.radians(-pitch))
    back_m = slant_km * 1000 * math.cos(math.radians(-pitch))
    lat_cam = max(-89.0, min(89.0, lat_c - back_m / 111_320))
    return {
        "lat": round(lat_cam, 6),
        "lon": round(lon_c, 6),
        "alt": round(alt_m, 1),
        "heading": 0,
        "pitch": pitch,
        "roll": 0,
    }


def _slug(text: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out[:60] or "board"


def build_scene(
    board: Board,
    include: str = "accepted",
    adapter: str = "scene-bundle",
    path_for=None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """The scene document and each pack's bytes, keyed by the pack's source path."""
    nodes, links = visible(board, include)
    if not nodes:
        raise ExportError(
            "Nothing to export: accept some of the board's suggestions first, or export "
            "with include=all"
        )
    by_id = {n.id: n for n in board.nodes}
    steps = plan_steps(board, nodes, links)
    if len(steps) > LIMITS["packs"]:
        raise ExportError("Too many time steps for one scene")
    geo = geometry(nodes)
    reasons: dict[int, list[str]] = defaultdict(list)
    for k in links:
        reasons[k.to_node_id].append(k.reason)

    scene_id = f"board-{board.id}"
    files, manifests = {}, []
    for i, step in enumerate(steps):
        data = pack_geojson(step, geo)
        path = path_for(step, i) if path_for else f"files/{i}-{_slug(step.id)}.geojson"
        files[path] = data
        manifest = {
            "id": step.id,
            "version": 1,
            "format": "geojson",
            "source": {"adapter": adapter, "path": path},
            # The globe shows one attribution card per loaded pack, so keep it short;
            # each feature's own card names its source.
            "attribution": {
                "text": f"{step.title}: UCDP, ACLED, GDELT, cited articles"
                + ("" if geo.real_heights else " (heights approximate)"),
                "license": "UCDP CC BY 4.0; ACLED terms; GDELT open; articles their publishers'",
            },
            "placement": {"altitudeReference": "ellipsoid"},
        }
        if adapter == "scene-bundle":
            manifest["byteLength"] = len(data)
            manifest["sha256"] = hashlib.sha256(data).hexdigest()
        manifests.append(manifest)

    shots = []
    # Open on the article and the places in the story's main countries, not on every
    # dateline and summit venue it mentions.
    framing = [
        n
        for n in steps[0].nodes
        if n.kind == "article" or (n.kind == "place" and n.attributes.get("focus", True))
    ]
    focus_points = [geo.positions[n.id][:2] for n in framing or steps[0].nodes] or [
        p[:2] for p in geo.positions.values()
    ]
    for i, step in enumerate(steps):
        # The story so far: context, then each step up to this one. History drops out once
        # the recent story starts, so the briefing stays readable.
        selected = [0] + (
            [i]
            if step.id == "history"
            else [j for j in range(1, i + 1) if steps[j].id != "history"]
        )
        selected = sorted(set(selected))
        new_points = [geo.positions[n.id][:2] for n in step.nodes] or focus_points
        if step.id == "context":
            new_points = focus_points
        shot = {
            "id": f"shot-{step.id}",
            "title": step.title[:200],
            "durationSec": 4,
            "holdSec": 8,
            "camera": _camera(new_points),
            "dataPackIds": [steps[j].id for j in selected],
            "interactions": _interactions(steps, selected, i, by_id, reasons),
        }
        shots.append(shot)

    now = now or datetime.now(UTC)
    if board.anchor_date and now.date() - board.anchor_date <= LIVE_WINDOW:
        last = dict(shots[-1])
        last.update(
            id="shot-now",
            title="Now: live military flights, GPS interference and fires",
            camera=_camera(focus_points),
            layers={layer: {"enabled": True} for layer in LIVE_LAYERS},
        )
        shots.append(last)

    project = {
        "version": SCENE_VERSION,
        "createdAt": board.created_at.isoformat() if board.created_at else now.isoformat(),
        "updatedAt": now.isoformat(),
        "scenes": [
            {
                "id": scene_id,
                "title": board.title[:200],
                "dataPacks": manifests,
                "shots": shots,
            }
        ],
    }
    return project, files


def _interactions(
    steps: list[Step],
    selected: list[int],
    current: int,
    by_id: dict[int, BoardNode],
    reasons: dict[int, list[str]],
) -> list[dict[str, Any]]:
    """Cards for the features in this shot, newest first, within the 64-card limit."""
    order = [current] + [j for j in reversed(selected) if j != current]
    items: list[dict[str, Any]] = []
    for j in order:
        step = steps[j]
        for n in step.nodes:
            items.append(
                _card(
                    step.id, n, node_card(n, reasons.get(n.id, [])), n.source_url, _node_button(n)
                )
            )
        for k in step.links:
            items.append(_card(step.id, k, link_card(k, by_id), None, _link_button(k, by_id)))
        if len(items) >= LIMITS["interactions"]:
            break
    return items[: LIMITS["interactions"]]


def _node_button(n: BoardNode) -> str:
    """The button in the globe's action list: what it is and when."""
    return f"{n.label} · {_day(utc_day(n.time_start))}" if n.time_start else n.label


def _link_button(k: BoardLink, by_id: dict[int, BoardNode]) -> str:
    a, b = by_id[k.from_node_id].label, by_id[k.to_node_id].label
    return f"Link: {_short(a)} → {_short(b)}"


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _card(
    pack_id: str, item: BoardNode | BoardLink, text: str, url: str | None, button: str
) -> dict[str, Any]:
    action: dict[str, Any] = {"type": "card", "text": text}
    if clean := clean_source_url(url):
        action["url"] = clean
    fid = _feature_id(item)
    return {
        "id": f"card-{fid}",
        "label": button[:256],
        "target": {"packId": pack_id, "featureId": fid},
        "action": action,
    }


def bundle(board: Board, include: str = "accepted", now: datetime | None = None) -> str:
    """A .gevbundle.json: the scene with its packs embedded, for the globe's IMPORT."""
    project, files = build_scene(board, include, adapter="scene-bundle", now=now)
    assets = [
        {
            "path": path,
            "mimeType": "application/geo+json",
            "base64": base64.b64encode(data).decode("ascii"),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for path, data in files.items()
    ]
    return json.dumps(
        {"format": "gev-scene-bundle", "version": 1, "project": project, "assets": assets},
        separators=(",", ":"),
    )


def filename(board: Board) -> str:
    return f"{_slug(board.title)}.gevbundle.json"
