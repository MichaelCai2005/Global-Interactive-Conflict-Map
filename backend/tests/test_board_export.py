import math
from datetime import UTC, date, datetime, timedelta

from app.boards import export, rules
from app.boards.models import Board, BoardLink, BoardNode


def node(id_, kind="event", lat=14.5, lon=-4.2, day=None, **attributes):
    return BoardNode(
        id=id_,
        key=f"k{id_}",
        kind=kind,
        label=f"{kind} {id_}",
        detail="",
        latitude=lat,
        longitude=lon,
        status="accepted",
        created_by="rule",
        attributes=attributes,
        time_start=datetime.combine(day, datetime.min.time(), tzinfo=UTC) if day else None,
    )


def test_arc_starts_and_ends_at_the_points_and_rises():
    a, b = (50.45, 30.52, 200.0), (55.75, 37.62, 150.0)
    positions = export.arc(a, b)
    assert positions[0] == [30.52, 50.45, 200.0]
    assert positions[-1][:2] == [37.62, 55.75] and positions[-1][2] == 150.0
    middle = positions[len(positions) // 2]
    assert middle[2] > 30_000  # ~750 km apart: the arc rises well above both ends


def test_arc_for_the_same_spot_is_a_small_loop():
    positions = export.arc((14.5, -4.2, 300.0), (14.5, -4.2, 300.0))
    assert all(p[:2] == [-4.2, 14.5] for p in positions)
    assert max(p[2] for p in positions) == 300.0 + 250.0


def test_spread_fans_out_points_that_share_a_spot():
    nodes = [node(i) for i in range(1, 5)] + [node(9, lat=10.0, lon=10.0)]
    shown = export._spread(nodes)
    assert shown[9] == (10.0, 10.0)
    ring = [shown[i] for i in range(1, 5)]
    assert len(set(ring)) == 4
    for lat, lon in ring:
        km = math.hypot((lat - 14.5) * 111.32, (lon + 4.2) * 111.32 * math.cos(math.radians(14.5)))
        assert 1.0 < km < 2.0


def test_plan_steps_orders_context_history_then_days():
    anchor = date(2026, 10, 16)
    board = Board(id=1, title="t", origin="manual", anchor_date=anchor)
    nodes = [
        node(1, "article", day=anchor),
        node(2, "place"),
        node(3, day=date(2024, 5, 1), history=True),
        node(4, day=date(2026, 10, 11)),
        node(5, day=date(2026, 10, 15)),
    ]
    links = [
        BoardLink(
            id=10,
            from_node_id=2,
            to_node_id=3,
            rule="history",
            reason="r",
            confidence=0.4,
            status="accepted",
            created_by="rule",
            evidence={},
        ),
        BoardLink(
            id=11,
            from_node_id=2,
            to_node_id=5,
            rule="near",
            reason="r",
            confidence=0.8,
            status="accepted",
            created_by="rule",
            evidence={},
        ),
    ]
    steps = export.plan_steps(board, nodes, links)
    assert [s.id for s in steps] == ["context", "history", "step-2026-10-11", "step-2026-10-15"]
    # A link appears in the step where its later end appears.
    assert [k.id for k in steps[1].links] == [10]
    assert [k.id for k in steps[3].links] == [11]


def test_many_days_are_grouped_into_at_most_five_steps():
    start = date(2026, 9, 1)
    nodes = [node(i, day=start + timedelta(days=i)) for i in range(1, 40)]
    steps = export._recent_steps(nodes)
    assert len(steps) <= export.MAX_RECENT_STEPS
    assert sum(len(s.nodes) for s in steps) == 39
    assert " to " in steps[0].title


def test_camera_frames_points_from_the_south():
    pose = export._camera([(50.0, 30.0), (51.0, 31.0)])
    assert pose["pitch"] == -65.0 and pose["lat"] < 50.0
    assert 30.0 <= pose["lon"] <= 31.0
    # Petersburg and Moscow: far enough back that both fit across the screen.
    wide = export._camera([(59.9, 30.3), (55.75, 37.6)])
    slant_km = wide["alt"] / 1000 / math.sin(math.radians(65))
    assert slant_km >= 1.6 * (37.6 - 30.3) * 111.32 * math.cos(math.radians(57.8))
    assert slant_km >= 2.3 * (59.9 - 55.75) * 111.32
    single = export._camera([(14.5, -4.2)])
    assert single["alt"] == round(40_000 * math.sin(math.radians(65)), 1)


def test_reason_wording():
    assert rules.when(0) == "the same day as"
    assert rules.when(-1) == "1 day before"
    assert rules.when(3) == "3 days after"
    assert rules.when(-400) == "about 13 months before"
    assert rules.when(-1100) == "about 3 years before"
    assert rules.near_confidence(0, 25, 0, 60) == 0.9
    assert rules.near_confidence(25, 25, 60, 60) == 0.2
