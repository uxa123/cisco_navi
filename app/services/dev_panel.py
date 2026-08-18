"""開発パネル向けの状態集約と通信元分類。"""

import re
from datetime import datetime, timezone

from app.repositories import (
    CommunicationLogRepository, NavigationSessionRepository, ObstacleRepository,
    PositionRepository,
)
from app.schemas.dev import DevClientState, DevLastAccess, DevStatusResponse

SESSION_PATH = re.compile(r"^/api/navigation/sessions/([^/]+)")


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
        self, positions: PositionRepository, sessions: NavigationSessionRepository,
        obstacles: ObstacleRepository, logs: CommunicationLogRepository,
    ) -> None:
        self.positions = positions
        self.sessions = sessions
        self.obstacles = obstacles
        self.logs = logs

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
