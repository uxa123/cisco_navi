"""試作段階の実行時状態を保持する、差し替え可能なメモリリポジトリ。"""

from collections import deque

from app.schemas.dev import CommunicationLog
from app.schemas.models import NavigationSession, NormalizedPosition, Obstacle


class PositionRepository:
    """クライアントごとの最新位置をメモリ上に保持する。"""

    def __init__(self) -> None:
        self._positions: dict[str, NormalizedPosition] = {}

    def save(self, position: NormalizedPosition) -> None:
        # 同じclient_idの位置は常に最新の受信値で置き換える。
        self._positions[position.client_id] = position

    def get_latest(self, client_id: str) -> NormalizedPosition | None:
        return self._positions.get(client_id)

    def list(self) -> list[NormalizedPosition]:
        return list(self._positions.values())

    def clear(self) -> None:
        self._positions.clear()


class ObstacleRepository:
    """現在通行止めになっているエッジをメモリ上に保持する。"""

    def __init__(self) -> None:
        self._obstacles: dict[str, Obstacle] = {}

    def save(self, obstacle: Obstacle) -> None:
        # blocked=falseは解除操作として扱い、一覧から削除する。
        if obstacle.blocked:
            self._obstacles[obstacle.edge_id] = obstacle
        else:
            self._obstacles.pop(obstacle.edge_id, None)

    def list(self) -> list[Obstacle]:
        return list(self._obstacles.values())

    def blocked_edge_ids(self) -> set[str]:
        return set(self._obstacles)

    def clear(self) -> None:
        self._obstacles.clear()


class NavigationSessionRepository:
    """ナビゲーションセッションをプロセス内に保持する。"""

    def __init__(self) -> None:
        self._sessions: dict[str, NavigationSession] = {}

    def save(self, session: NavigationSession) -> None:
        self._sessions[session.session_id] = session

    def get(self, session_id: str) -> NavigationSession | None:
        return self._sessions.get(session_id)

    def active_for_client(self, client_id: str) -> list[NavigationSession]:
        return [session for session in self._sessions.values()
                if session.client_id == client_id and session.status == "active"]

    def list(self) -> list[NavigationSession]:
        return list(self._sessions.values())

    def clear(self) -> None:
        self._sessions.clear()


class CommunicationLogRepository:
    """機密情報やBodyを含めず、直近のHTTPメタデータだけを保持する。"""

    def __init__(self, max_entries: int = 100) -> None:
        self._entries: deque[CommunicationLog] = deque(maxlen=max_entries)

    def save(self, entry: CommunicationLog) -> None:
        self._entries.append(entry)

    def list(self) -> list[CommunicationLog]:
        return list(reversed(self._entries))

    def clear(self) -> None:
        self._entries.clear()
