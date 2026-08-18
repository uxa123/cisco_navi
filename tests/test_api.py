"""本番用地図から独立した小規模グラフを使用するAPIテスト。"""

import json

import asyncio

import httpx
import pytest

from app.main import create_app


class ApiClient:
    """HTTPXのASGIトランスポートを同期テストから扱うための薄いラッパー。"""

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
def client(tmp_path) -> ApiClient:
    # 最短経路と迂回経路を明確に検証できる専用地図をテストごとに生成する。
    map_data = {
        "floors": [{
            "floor_id": "floor-1", "name": "Test floor",
            "nodes": [
                {"id": "start", "name": "入口", "floor_id": "floor-1", "x": 0, "y": 0, "type": "entrance"},
                {"id": "short", "name": "近道", "floor_id": "floor-1", "x": 5, "y": 0, "type": "corridor"},
                {"id": "upper", "name": "迂回路1", "floor_id": "floor-1", "x": 0, "y": 5, "type": "corner"},
                {"id": "lower", "name": "迂回路2", "floor_id": "floor-1", "x": 5, "y": 5, "type": "corner"},
                {"id": "goal", "name": "教室", "floor_id": "floor-1", "x": 10, "y": 0, "type": "room", "selectable": True},
            ],
            "edges": [
                {"id": "direct-1", "from": "start", "to": "short", "distance": 5, "bidirectional": True},
                {"id": "direct-2", "from": "short", "to": "goal", "distance": 5, "bidirectional": True},
                {"id": "detour-1", "from": "start", "to": "upper", "distance": 6, "bidirectional": True},
                {"id": "detour-2", "from": "upper", "to": "lower", "distance": 6, "bidirectional": True},
                {"id": "detour-3", "from": "lower", "to": "goal", "distance": 6, "bidirectional": True},
            ],
        }]
    }
    path = tmp_path / "map.json"
    path.write_text(json.dumps(map_data), encoding="utf-8")
    return ApiClient(create_app(path))


def register(client: ApiClient) -> None:
    response = client.post("/api/mock/positions", json={
        "client_id": "user-1", "floor_id": "floor-1", "x": 0.2, "y": 0.1,
        "variance": 1.5, "observed_at": "2026-07-30T10:00:00+09:00",
    })
    assert response.status_code == 200


def test_health(client: ApiClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_local_test_web_origin_is_allowed(client: ApiClient) -> None:
    """独立したローカル検証画面からAPIを呼び出せることを確認する。"""
    response = client.request(
        "OPTIONS",
        "/api/maps/floor-1",
        headers={
            "Origin": "http://127.0.0.1:8080",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8080"


def test_get_map_and_missing_map(client: ApiClient) -> None:
    response = client.get("/api/maps/floor-1")
    assert response.status_code == 200
    assert len(response.json()["nodes"]) == 5
    assert response.json()["edges"][0]["from"] == "start"
    nodes = {node["id"]: node for node in response.json()["nodes"]}
    assert nodes["goal"]["selectable"] is True
    # selectableを省略した既存地図ノードは互換性のためfalseになる。
    assert nodes["start"]["selectable"] is False
    assert {"id", "name", "floor_id", "x", "y", "type", "selectable"} <= nodes["goal"].keys()
    assert client.get("/api/maps/missing").status_code == 404


def test_mock_position_and_nearest_node(client: ApiClient) -> None:
    register(client)
    response = client.get("/api/positions/user-1")
    assert response.status_code == 200
    assert response.json()["nearest_node"] == {"id": "start", "name": "入口", "distance": 0.22}
    assert response.json()["source"] == "mock"


def test_shortest_route_and_guidance(client: ApiClient) -> None:
    register(client)
    response = client.post("/api/routes/search", json={"client_id": "user-1", "destination_node_id": "goal"})
    assert response.status_code == 200
    body = response.json()
    assert [node["id"] for node in body["route"]] == ["start", "short", "goal"]
    assert body["total_distance"] == 10
    assert body["guidance"][-1]["type"] == "arrive"
    assert {step["type"] for step in body["guidance"]} >= {"straight", "arrive"}


def test_obstacle_selects_detour_and_unblock_restores_route(client: ApiClient) -> None:
    register(client)
    blocked = client.post("/api/obstacles", json={
        "edge_id": "direct-1", "blocked": True, "reason": "chair", "source": "mock",
    })
    assert blocked.status_code == 200
    assert client.get("/api/obstacles").json()[0]["edge_id"] == "direct-1"
    detour = client.post("/api/routes/search", json={"client_id": "user-1", "destination_node_id": "goal"})
    assert [node["id"] for node in detour.json()["route"]] == ["start", "upper", "lower", "goal"]
    assert {step["type"] for step in detour.json()["guidance"]} >= {"right", "arrive"}

    unblocked = client.post("/api/obstacles", json={
        "edge_id": "direct-1", "blocked": False, "reason": None, "source": "mock",
    })
    assert unblocked.status_code == 200
    restored = client.post("/api/routes/search", json={"client_id": "user-1", "destination_node_id": "goal"})
    assert [node["id"] for node in restored.json()["route"]] == ["start", "short", "goal"]


def test_all_routes_blocked_returns_conflict(client: ApiClient) -> None:
    register(client)
    for edge_id in ("direct-1", "detour-1"):
        assert client.post("/api/obstacles", json={"edge_id": edge_id, "blocked": True}).status_code == 200
    response = client.post("/api/routes/search", json={"client_id": "user-1", "destination_node_id": "goal"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ROUTE_NOT_FOUND"


def test_missing_destination_and_client(client: ApiClient) -> None:
    missing_client = client.post("/api/routes/search", json={"client_id": "nobody", "destination_node_id": "goal"})
    assert missing_client.status_code == 404
    assert missing_client.json()["detail"]["code"] == "POSITION_NOT_FOUND"
    register(client)
    missing_destination = client.post("/api/routes/search", json={"client_id": "user-1", "destination_node_id": "missing"})
    assert missing_destination.status_code == 404
    assert missing_destination.json()["detail"]["code"] == "DESTINATION_NOT_FOUND"


def test_missing_edge(client: ApiClient) -> None:
    response = client.post("/api/obstacles", json={"edge_id": "missing", "blocked": True})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EDGE_NOT_FOUND"
