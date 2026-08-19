"""開発パネル、通信ログ、既存API経由のデバッグ操作。"""

import asyncio
import json

import httpx
import pytest

from app.main import create_app


class Client:
    def __init__(self, app) -> None:
        self.app = app

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async def send() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app), base_url="http://test",
            ) as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(send())

    def get(self, path: str) -> httpx.Response:
        return self.request("GET", path)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)


@pytest.fixture()
def dev_client(tmp_path) -> Client:
    map_data = {"floors": [{
        "floor_id": "floor-1", "name": "Test",
        "nodes": [
            {"id": "start", "name": "入口", "floor_id": "floor-1", "x": 0, "y": 0, "type": "entrance"},
            {"id": "goal", "name": "目的地", "floor_id": "floor-1", "x": 10, "y": 0, "type": "room"},
        ],
        "edges": [{"id": "edge-1", "from": "start", "to": "goal", "distance": 10}],
    }]}
    path = tmp_path / "map.json"
    path.write_text(json.dumps(map_data), encoding="utf-8")
    return Client(create_app(path, dev_panel_enabled=True))


def scanning_payload(client_id: str, x: float) -> dict:
    timestamp = "2026-08-18T16:00:00+09:00"
    return {
        "version": "3.0", "secret": "not-logged", "type": "WiFi",
        "data": {"networkId": "L_TEST", "observations": [{
            "clientMac": client_id,
            "locations": [{
                "x": str(x), "y": "0", "floorPlanId": "floor-1",
                "floorPlanName": "Test", "time": timestamp, "variance": 1.5,
                "rssiRecords": [],
            }],
            "latestRecord": {"time": timestamp},
        }]},
    }


def test_dev_panel_can_be_disabled() -> None:
    client = Client(create_app(dev_panel_enabled=False))
    assert client.get("/dev").status_code == 404
    assert client.get("/api/dev/status").status_code == 404
    assert client.get("/api/health").status_code == 200


def test_dev_panel_page_and_assets(dev_client: Client) -> None:
    page = dev_client.get("/dev")
    assert page.status_code == 200
    assert "Development Console" in page.text
    assert page.headers["cache-control"] == "no-store, max-age=0"
    assert dev_client.get("/dev/assets/dev.css").status_code == 200
    script = dev_client.get("/dev/assets/dev.js")
    assert script.status_code == 200
    assert script.headers["cache-control"] == "no-store, max-age=0"
    assert "map.nodes.map" in script.text


def test_dev_mock_route_and_payload_use_existing_scanning_format(dev_client: Client) -> None:
    route = dev_client.get("/api/dev/mock/route")
    assert route.status_code == 200
    body = route.json()
    assert body["floor_id"] == "floor-1"
    assert [(point["x"], point["y"]) for point in body["points"]] == [
        (0.0, 0.0), (2.5, 0.0), (5.0, 0.0), (5.0, 2.5),
        (5.0, 5.0), (10.0, 5.0), (15.0, 5.0),
    ]
    generated = dev_client.post("/api/dev/mock/payload", json={
        "client_id": "mock-user-01", "x": 5, "y": 0, "scenario": "normal",
    })
    assert generated.status_code == 200
    payload = generated.json()["payload"]
    assert payload["version"] == "3.0"
    assert payload["data"]["observations"][0]["clientMac"] == "mock-user-01"
    assert payload["data"]["observations"][0]["locations"][0]["floorPlanId"] == "floor-1"
    # Payload生成だけでは位置Repositoryを更新しない。必ず/api/scanningへの送信が必要。
    assert dev_client.get("/api/positions/mock-user-01").status_code == 404


def test_integration_operations_logs_and_reset(dev_client: Client) -> None:
    mock = dev_client.post("/api/mock/positions", json={
        "client_id": "mock-user-01", "floor_id": "floor-1", "x": 0, "y": 0,
        "variance": 1.5, "observed_at": "2026-08-18T15:59:00+09:00",
    })
    assert mock.status_code == 200

    created = dev_client.post("/api/navigation/sessions", json={
        "client_id": "mock-user-01", "destination_id": "goal",
    })
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    movement = dev_client.post(f"/api/navigation/sessions/{session_id}/movements", json={
        "sequence": 1, "distance_m": 1, "heading_deg": 90,
        "timestamp": "2026-08-18T16:00:01+09:00",
    })
    assert movement.status_code == 200
    assert dev_client.get(f"/api/navigation/sessions/{session_id}/state").status_code == 200

    scanning = dev_client.post("/api/scanning", json=scanning_payload("mock-user-01", 4))
    assert scanning.status_code == 200
    state = dev_client.get(f"/api/navigation/sessions/{session_id}/state").json()
    assert state["position_state"]["fused_position"]["source"] == "meraki_correction"

    assert dev_client.post("/api/obstacles", json={
        "edge_id": "edge-1", "blocked": True, "reason": "test", "source": "dev-panel",
    }).status_code == 200
    assert dev_client.post("/api/obstacles", json={
        "edge_id": "edge-1", "blocked": False, "reason": None, "source": "dev-panel",
    }).status_code == 200

    status = dev_client.get("/api/dev/status")
    assert status.status_code == 200
    body = status.json()
    assert body["backend_status"] == "ONLINE"
    assert body["active_clients"] == 1
    assert len(body["clients"]) == 1
    assert len(body["sessions"]) == 1
    paths = {entry["path"] for entry in body["communication_logs"]}
    assert "/api/scanning" in paths
    assert f"/api/navigation/sessions/{session_id}/movements" in paths
    assert f"/api/navigation/sessions/{session_id}/state" in paths
    scanning_log = next(entry for entry in body["communication_logs"] if entry["path"] == "/api/scanning")
    assert scanning_log["source"] == "Meraki / Scanning"
    assert "secret" not in scanning_log

    finished = dev_client.request("DELETE", f"/api/navigation/sessions/{session_id}")
    assert finished.status_code == 200
    assert finished.json()["status"] == "finished"

    reset = dev_client.post("/api/dev/reset", json={})
    assert reset.status_code == 200
    cleared = dev_client.get("/api/dev/status").json()
    assert cleared["clients"] == []
    assert cleared["sessions"] == []
    assert cleared["obstacles"] == []
    assert cleared["communication_logs"] == []
