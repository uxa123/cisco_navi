"""開発パネル専用の読み取りモデル。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.models import NavigationSession, NormalizedPosition, Obstacle


CommunicationSource = Literal["Android (推定)", "Meraki / Scanning", "Dev Panel", "Other"]


class CommunicationLog(BaseModel):
    timestamp: datetime
    method: str
    path: str
    status_code: int
    duration_ms: float
    source: CommunicationSource
    client_id: str | None = None
    session_id: str | None = None


class DevClientState(BaseModel):
    client_id: str
    latest_position: NormalizedPosition
    navigation_session: NavigationSession | None = None


class DevLastAccess(BaseModel):
    android: datetime | None = None
    scanning: datetime | None = None
    movement: datetime | None = None
    state_poll: datetime | None = None


class DevStatusResponse(BaseModel):
    backend_status: Literal["ONLINE"] = "ONLINE"
    current_time: datetime
    active_clients: int
    active_navigation_sessions: int
    blocked_edges: int
    last_access: DevLastAccess
    clients: list[DevClientState]
    sessions: list[NavigationSession]
    obstacles: list[Obstacle]
    communication_logs: list[CommunicationLog]


class DevResetResponse(BaseModel):
    message: str
