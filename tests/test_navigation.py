"""セッション、PDR、位置融合、マップマッチング、経路追従のテスト。"""

import asyncio
import json
from datetime import datetime, timezone

import pytest
import httpx

from app.schemas.models import FloorMap, MovementRequest, NavigationCurrentPosition, NavigationPoint
from app.services.map_matching import MapMatchingService
from app.services.navigation import absolute_heading_deg
from app.services.navigation_session import NavigationSessionService
from app.services.pdr import PdrService
from app.main import create_app


class ApiClient:
    def __init__(self, app) -> None:
        self.app = app

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, url, **kwargs)
        return asyncio.run(send())

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)


@pytest.fixture()
def nav_client(tmp_path) -> ApiClient:
    data = {"floors": [{
        "floor_id": "floor-1", "name": "Test",
        "nodes": [
            {"id": "start", "name": "入口", "floor_id": "floor-1", "x": 0, "y": 0, "type": "entrance"},
            {"id": "middle", "name": "中央", "floor_id": "floor-1", "x": 5, "y": 0, "type": "corridor"},
            {"id": "upper", "name": "上側", "floor_id": "floor-1", "x": 0, "y": 5, "type": "corridor"},
            {"id": "upper-right", "name": "上側右", "floor_id": "floor-1", "x": 10, "y": 5, "type": "corridor"},
            {"id": "goal", "name": "目的地", "floor_id": "floor-1", "x": 10, "y": 0, "type": "room"},
            {"id": "north-goal", "name": "北側目的地", "floor_id": "floor-1", "x": 5, "y": 5, "type": "room"},
        ],
        "edges": [
            {"id": "direct-1", "from": "start", "to": "middle", "distance": 5},
            {"id": "direct-2", "from": "middle", "to": "goal", "distance": 5},
            {"id": "detour-1", "from": "start", "to": "upper", "distance": 5},
            {"id": "detour-2", "from": "upper", "to": "upper-right", "distance": 10},
            {"id": "detour-3", "from": "upper-right", "to": "goal", "distance": 5},
            {"id": "turn-north", "from": "middle", "to": "north-goal", "distance": 5},
        ],
    }]}
    path = tmp_path / "map.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return ApiClient(create_app(path))


def register(client: ApiClient, client_id: str = "user-1", x: float = 0, y: float = 0) -> None:
    assert client.post("/api/mock/positions", json={
        "client_id": client_id, "floor_id": "floor-1", "x": x, "y": y,
        "observed_at": "2026-08-17T19:00:00+09:00",
    }).status_code == 200


def start(client: ApiClient, client_id: str = "user-1") -> dict:
    response = client.post("/api/navigation/sessions", json={
        "client_id": client_id, "destination_id": "goal",
    })
    assert response.status_code == 201
    return response.json()


def movement(client: ApiClient, session_id: str, sequence: int, distance: float, heading: float) -> dict:
    response = client.post(f"/api/navigation/sessions/{session_id}/movements", json={
        "sequence": sequence, "distance_m": distance, "heading_deg": heading,
        "timestamp": f"2026-08-17T19:00:{sequence:02d}+09:00",
    })
    assert response.status_code == 200
    return response.json()


def test_session_lifecycle_and_errors(nav_client: ApiClient) -> None:
    assert nav_client.post("/api/navigation/sessions", json={"client_id": "missing", "destination_id": "goal"}).status_code == 404
    register(nav_client)
    assert nav_client.post("/api/navigation/sessions", json={"client_id": "user-1", "destination_id": "missing"}).status_code == 404
    created = start(nav_client)
    assert created["status"] == "active"
    assert nav_client.get(f"/api/navigation/sessions/{created['session_id']}").status_code == 200
    finished = nav_client.request("DELETE", f"/api/navigation/sessions/{created['session_id']}")
    assert finished.json()["status"] == "finished"
    rejected = nav_client.post(f"/api/navigation/sessions/{created['session_id']}/movements", json={
        "sequence": 1, "distance_m": 1, "heading_deg": 90,
        "timestamp": "2026-08-17T19:00:01+09:00",
    })
    assert rejected.status_code == 409


@pytest.mark.parametrize(("heading", "expected"), [
    (0, (0, 1)), (90, (1, 0)), (180, (0, -1)), (270, (-1, 0)),
])
def test_pdr_cardinal_directions(heading: float, expected: tuple[float, float]) -> None:
    origin = NavigationPoint(floor_id="f", x=0, y=0, observed_at=datetime.now(timezone.utc), source="meraki")
    request = MovementRequest(sequence=1, distance_m=1, heading_deg=heading, timestamp=datetime.now(timezone.utc))
    result = PdrService().apply(origin, request)
    assert result.x == pytest.approx(expected[0], abs=1e-9)
    assert result.y == pytest.approx(expected[1], abs=1e-9)


@pytest.mark.parametrize(("target", "expected"), [
    ((0, 5), 0), ((5, 0), 90), ((0, -5), 180), ((-5, 0), 270),
    ((5, 5), 45), ((5, -5), 135), ((-5, -5), 225), ((-5, 5), 315),
])
def test_absolute_target_heading(target: tuple[float, float], expected: float) -> None:
    assert absolute_heading_deg(0, 0, *target) == pytest.approx(expected)


def test_target_heading_is_none_for_same_point() -> None:
    assert absolute_heading_deg(1, 1, 1, 1) is None
    current = NavigationCurrentPosition(floor_id="f", x=1, y=1, source="test")
    assert NavigationSessionService._guidance_for_route(current, []) is None


def test_target_heading_changes_at_corner_and_is_none_on_arrival(nav_client: ApiClient) -> None:
    register(nav_client, "turn-user")
    created = nav_client.post("/api/navigation/sessions", json={
        "client_id": "turn-user", "destination_id": "north-goal",
    })
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    assert created.json()["next_guidance"]["target_heading_deg"] == pytest.approx(90)

    at_corner = movement(nav_client, session_id, 1, 5, 90)
    assert at_corner["next_guidance"]["action"] == "left"
    assert at_corner["next_guidance"]["target_heading_deg"] == pytest.approx(0)
    state = nav_client.get(f"/api/navigation/sessions/{session_id}/state").json()
    assert state["next_guidance"]["target_heading_deg"] == pytest.approx(0)

    arrived = movement(nav_client, session_id, 2, 5, 0)
    assert arrived["status"] == "arrived"
    assert arrived["next_guidance"]["target_heading_deg"] is None
    fetched = nav_client.get(f"/api/navigation/sessions/{session_id}").json()
    assert fetched["next_guidance"]["target_heading_deg"] is None


def test_replanned_route_updates_target_heading(nav_client: ApiClient) -> None:
    register(nav_client, "reroute-user")
    created = start(nav_client, "reroute-user")
    assert created["next_guidance"]["target_heading_deg"] == pytest.approx(90)
    assert nav_client.post("/api/obstacles", json={
        "edge_id": "direct-1", "blocked": True,
    }).status_code == 200
    state = nav_client.get(f"/api/navigation/sessions/{created['session_id']}/state").json()
    assert state["route_changed"] is True
    assert state["next_guidance"]["target_heading_deg"] == pytest.approx(0)


def test_pdr_accumulates_and_duplicate_sequence_is_idempotent(nav_client: ApiClient) -> None:
    register(nav_client)
    session_id = start(nav_client)["session_id"]
    movement(nav_client, session_id, 1, 1, 90)
    second = movement(nav_client, session_id, 2, 1, 90)
    duplicate = movement(nav_client, session_id, 2, 1, 90)
    assert second["position_state"]["pdr_position"]["x"] == pytest.approx(2)
    assert duplicate["duplicate"] is True
    assert duplicate["position_state"]["pdr_position"]["x"] == pytest.approx(2)


def meraki_payload(client_id: str, x: float, y: float) -> dict:
    return {"version": "3.0", "secret": "test", "type": "WiFi", "data": {
        "networkId": "N", "observations": [{"clientMac": client_id, "locations": [{
            "x": str(x), "y": str(y), "floorPlanId": "floor-1",
            "time": "2026-08-17T19:05:00+09:00", "variance": 1,
        }], "latestRecord": {"time": "2026-08-17T19:05:00+09:00"}}],
    }}


def test_meraki_correction_resets_only_matching_client(nav_client: ApiClient) -> None:
    register(nav_client, "one")
    register(nav_client, "two")
    one, two = start(nav_client, "one"), start(nav_client, "two")
    movement(nav_client, one["session_id"], 1, 2, 90)
    before_two = nav_client.get(f"/api/navigation/sessions/{two['session_id']}/state").json()
    assert nav_client.post("/api/scanning", json=meraki_payload("one", 4, 0)).status_code == 200
    corrected = nav_client.get(f"/api/navigation/sessions/{one['session_id']}/state").json()
    after_two = nav_client.get(f"/api/navigation/sessions/{two['session_id']}/state").json()
    assert corrected["position_state"]["fused_position"]["x"] == 4
    assert corrected["position_state"]["fused_position"]["source"] == "meraki_correction"
    assert after_two["position_state"] == before_two["position_state"]


def floor_for_matching() -> FloorMap:
    return FloorMap.model_validate({"floor_id": "f", "name": "F", "nodes": [
        {"id": "a", "name": "A", "floor_id": "f", "x": 0, "y": 0, "type": "c"},
        {"id": "b", "name": "B", "floor_id": "f", "x": 10, "y": 0, "type": "c"},
        {"id": "c", "name": "C", "floor_id": "f", "x": 10, "y": 10, "type": "c"},
        {"id": "d", "name": "D", "floor_id": "f", "x": 20, "y": 10, "type": "c"},
    ], "edges": [
        {"id": "horizontal", "from": "a", "to": "b", "distance": 10},
        {"id": "vertical", "from": "b", "to": "c", "distance": 10},
        {"id": "diagonal", "from": "a", "to": "c", "distance": 14.14},
    ]})


@pytest.mark.parametrize(("x", "y", "edge", "matched"), [
    (5, 0.5, "horizontal", (5, 0)), (10.5, 7, "vertical", (10, 7)), (4, 5, "diagonal", (4.5, 4.5)),
])
def test_map_matching_horizontal_vertical_diagonal(x, y, edge, matched) -> None:
    point = NavigationPoint(floor_id="f", x=x, y=y, observed_at=datetime.now(timezone.utc), source="pdr")
    result = MapMatchingService().match(floor_for_matching(), point)
    assert result.edge.id == edge
    assert (result.matched_position.x, result.matched_position.y) == pytest.approx(matched)


def test_map_matching_intersection_and_far_position() -> None:
    floor = floor_for_matching()
    point = NavigationPoint(floor_id="f", x=10, y=0, observed_at=datetime.now(timezone.utc), source="pdr")
    assert MapMatchingService().match(floor, point).edge.id in {"horizontal", "vertical", "diagonal"}
    far = point.model_copy(update={"x": 100, "y": 100})
    result = MapMatchingService(max_distance_m=3).match(floor, far)
    assert result.matched is False
    assert (result.matched_position.x, result.matched_position.y) == (100, 100)


def test_route_following_off_route_obstacle_and_arrival(nav_client: ApiClient) -> None:
    register(nav_client)
    session = start(nav_client)
    followed = movement(nav_client, session["session_id"], 1, 2, 90)
    assert followed["route_changed"] is False
    assert followed["remaining_distance_m"] == pytest.approx(8)

    off_route = movement(nav_client, session["session_id"], 2, 5, 0)
    assert off_route["route_changed"] is True

    register(nav_client, "blocked-user")
    blocked_session = start(nav_client, "blocked-user")
    assert nav_client.post("/api/obstacles", json={"edge_id": "direct-2", "blocked": True}).status_code == 200
    blocked_state = nav_client.get(f"/api/navigation/sessions/{blocked_session['session_id']}/state").json()
    assert blocked_state["route_changed"] is True

    register(nav_client, "arrival-user")
    arrival = start(nav_client, "arrival-user")
    arrived = movement(nav_client, arrival["session_id"], 1, 10, 90)
    assert arrived["status"] == "arrived"
    assert arrived["remaining_distance_m"] == 0
