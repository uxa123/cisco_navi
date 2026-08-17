"""Scanning APIモック生成と受信エンドポイントのテスト。"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.main import create_app
from app.services.scanning_mock_service import (
    AccessPoint, MockDataError, MockRoute, RoutePosition, ScanningMockService, load_route,
)


@pytest.fixture()
def route() -> MockRoute:
    return MockRoute.model_validate({
        "floorPlanId": "floor-1", "floorPlanName": "1階",
        "positions": [{"x": 0, "y": 0}, {"x": 5, "y": 0}],
    })


@pytest.fixture()
def aps() -> list[AccessPoint]:
    return [
        AccessPoint(mac="aa:00:00:00:00:01", name="AP-1", x=0, y=0),
        AccessPoint(mac="aa:00:00:00:00:02", name="AP-2", x=20, y=0),
    ]


def make_payload(
    service: ScanningMockService, route: MockRoute, position: RoutePosition,
    observed_at: datetime | None = None, scenario: str = "normal",
) -> dict:
    return service.build_payload(
        route=route, position=position, observed_at=observed_at or datetime.now(timezone.utc),
        client_mac="cc:cc:cc:11:11:11", network_id="L_TEST", secret="test-secret", scenario=scenario,
    )


def test_generates_wifi_payload_with_string_coordinates(route: MockRoute, aps: list[AccessPoint]) -> None:
    payload = make_payload(ScanningMockService(aps, seed=1), route, route.positions[1])
    location = payload["data"]["observations"][0]["locations"][0]
    assert payload["version"] == "3.0"
    assert payload["type"] == "WiFi"
    assert isinstance(location["x"], str)
    assert isinstance(location["y"], str)
    assert [position.x for position in route.positions] == [0, 5]


def test_timestamp_is_updated(route: MockRoute, aps: list[AccessPoint]) -> None:
    service = ScanningMockService(aps, seed=1)
    first = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    second = first + timedelta(seconds=5)
    first_payload = make_payload(service, route, route.positions[0], first)
    second_payload = make_payload(service, route, route.positions[0], second)
    first_time = first_payload["data"]["observations"][0]["latestRecord"]["time"]
    second_time = second_payload["data"]["observations"][0]["latestRecord"]["time"]
    assert first_time != second_time
    assert second_time == second.isoformat()


def test_rssi_uses_distance_and_selects_strongest_ap(route: MockRoute, aps: list[AccessPoint]) -> None:
    payload = make_payload(ScanningMockService(aps, seed=3), route, route.positions[0])
    observation = payload["data"]["observations"][0]
    records = observation["locations"][0]["rssiRecords"]
    assert records[0]["rssi"] > records[1]["rssi"]
    assert observation["latestRecord"]["nearestApMac"] == records[0]["apMac"]


def test_location_unavailable_has_no_locations(route: MockRoute, aps: list[AccessPoint]) -> None:
    payload = make_payload(
        ScanningMockService(aps, seed=1), route, route.positions[0], scenario="location-unavailable"
    )
    observation = payload["data"]["observations"][0]
    assert observation["locations"] == []
    assert observation["latestRecord"]["nearestApMac"]


def test_same_seed_produces_same_result(route: MockRoute, aps: list[AccessPoint]) -> None:
    observed_at = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    first = make_payload(ScanningMockService(aps, seed=99), route, route.positions[1], observed_at, "noisy")
    second = make_payload(ScanningMockService(aps, seed=99), route, route.positions[1], observed_at, "noisy")
    assert first == second


def test_invalid_route_file_raises_clear_error(tmp_path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"floorPlanId": "floor-1", "positions": []}), encoding="utf-8")
    with pytest.raises(MockDataError, match="経路ファイルの形式が不正"):
        load_route(path)


def api_request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(send())


def test_scanning_endpoint_updates_latest_position(route: MockRoute, aps: list[AccessPoint]) -> None:
    app = create_app()
    payload = make_payload(ScanningMockService(aps, seed=1), route, route.positions[1])
    received = api_request(app, "POST", "/api/scanning", json=payload)
    assert received.status_code == 200
    assert received.json() == {
        "received": 1, "updated": 1, "skipped": 0, "client_ids": ["cc:cc:cc:11:11:11"]
    }
    latest = api_request(app, "GET", "/api/positions/cc:cc:cc:11:11:11")
    assert latest.status_code == 200
    assert latest.json()["position"] == {"floor_id": "floor-1", "x": 5.0, "y": 0.0}
    assert latest.json()["source"] == "meraki"


def test_unavailable_location_does_not_overwrite_latest(route: MockRoute, aps: list[AccessPoint]) -> None:
    app = create_app()
    service = ScanningMockService(aps, seed=1)
    api_request(app, "POST", "/api/scanning", json=make_payload(service, route, route.positions[1]))
    unavailable = make_payload(service, route, route.positions[0], scenario="location-unavailable")
    received = api_request(app, "POST", "/api/scanning", json=unavailable)
    assert received.json()["skipped"] == 1
    latest = api_request(app, "GET", "/api/positions/cc:cc:cc:11:11:11").json()
    assert latest["position"]["x"] == 5.0
