"""開発パネル向けの状態集約と通信元分類。"""

import re
from datetime import datetime, timezone
from pathlib import Path

from app.repositories import (
    CommunicationLogRepository, NavigationSessionRepository, ObstacleRepository,
    PositionRepository,
)
from app.schemas.dev import (
    DevClientState, DevLastAccess, DevMockPayloadRequest, DevMockPayloadResponse,
    DevMockPoint, DevMockRouteResponse, DevStatusResponse,
)
from app.services.navigation import find_nearest_node
from app.services.scanning_mock_service import (
    MockRoute, RoutePosition, ScanningMockService, load_access_points, load_route,
)

SESSION_PATH = re.compile(r"^/api/navigation/sessions/([^/]+)")
MOCK_DATA_DIR = Path(__file__).resolve().parents[2] / "scripts" / "mock_data"


def classify_source(path: str) -> str:
    if path == "/api/scanning":
        return "Meraki / Scanning"
    if path == "/dev" or path.startswith("/dev/") or path.startswith("/api/dev/"):
        return "Dev Panel"
    if path == "/api/navigation/sessions" or path.startswith("/api/navigation/sessions/"):
        return "Android (推定)"
    return "Other"


def session_id_from_path(path: str) -> str | None:
    match = SESSION_PATH.match(path)
    return match.group(1) if match else None


class DevPanelService:
    def __init__(
        self, maps, positions: PositionRepository, sessions: NavigationSessionRepository,
        obstacles: ObstacleRepository, logs: CommunicationLogRepository,
    ) -> None:
        self.maps = maps
        self.positions = positions
        self.sessions = sessions
        self.obstacles = obstacles
        self.logs = logs
        self._mock_service: ScanningMockService | None = None

    def mock_route(self) -> DevMockRouteResponse:
        route = load_route(MOCK_DATA_DIR / "floor_1_route.json")
        floor = self.maps.get_floor(route.floor_plan_id)
        points = []
        for index, position in enumerate(route.positions):
            node_id = node_name = None
            if floor is not None:
                nearest, distance = find_nearest_node(floor, position.x, position.y)
                if distance < 0.01:
                    node_id, node_name = nearest.id, nearest.name
            points.append(DevMockPoint(
                index=index, x=position.x, y=position.y,
                wait_seconds=position.wait_seconds, node_id=node_id, node_name=node_name,
            ))
        return DevMockRouteResponse(
            floor_id=route.floor_plan_id, floor_name=route.floor_plan_name, points=points,
        )

    def mock_payload(self, request: DevMockPayloadRequest) -> DevMockPayloadResponse:
        route_data = self.mock_route()
        route = MockRoute(
            floorPlanId=route_data.floor_id, floorPlanName=route_data.floor_name,
            positions=[RoutePosition(x=request.x, y=request.y)],
        )
        if self._mock_service is None:
            self._mock_service = ScanningMockService(
                load_access_points(MOCK_DATA_DIR / "ap_positions.json"), seed=42,
            )
        payload = self._mock_service.build_payload(
            route=route, position=route.positions[0], observed_at=datetime.now(timezone.utc),
            client_mac=request.client_id, network_id="L_TEST", secret="test-secret",
            scenario=request.scenario,
        )
        return DevMockPayloadResponse(payload=payload)

    def status(self) -> DevStatusResponse:
        sessions = self.sessions.list()
        entries = self.logs.list()
        clients = []
        for position in self.positions.list():
            related = [item for item in sessions if item.client_id == position.client_id]
            latest = max(related, key=lambda item: item.updated_at) if related else None
            clients.append(DevClientState(
                client_id=position.client_id, latest_position=position,
                navigation_session=latest,
            ))

        def last_timestamp(predicate) -> datetime | None:
            entry = next((item for item in entries if predicate(item)), None)
            return entry.timestamp if entry else None

        return DevStatusResponse(
            current_time=datetime.now(timezone.utc),
            active_clients=len(self.positions.list()),
            active_navigation_sessions=sum(item.status == "active" for item in sessions),
            blocked_edges=len(self.obstacles.list()),
            last_access=DevLastAccess(
                android=last_timestamp(lambda item: item.source == "Android (推定)"),
                scanning=last_timestamp(lambda item: item.path == "/api/scanning"),
                movement=last_timestamp(lambda item: item.path.endswith("/movements")),
                state_poll=last_timestamp(lambda item: item.path.endswith("/state")),
            ),
            clients=clients, sessions=sessions, obstacles=self.obstacles.list(),
            communication_logs=entries,
        )

    def reset(self) -> None:
        self.positions.clear()
        self.sessions.clear()
        self.obstacles.clear()
        self.logs.clear()
        self._mock_service = None
