"""FastAPIアプリケーションのエントリーポイント。"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.repositories import (
    CommunicationLogRepository, JsonMapRepository, MapDataError, NavigationSessionRepository,
    ObstacleRepository, PositionRepository,
)
from app.middleware import DevelopmentCommunicationMiddleware
from app.routers.api import router
from app.routers.dev import router as dev_router
from app.routers.navigation import router as navigation_router
from app.services.dev_panel import DevPanelService
from app.services.navigation_session import NavigationSessionService

logger = logging.getLogger(__name__)
DEFAULT_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "facility_map.json"


def _dev_panel_enabled(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    return os.getenv("DEV_PANEL_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def create_app(map_path: Path | None = None, dev_panel_enabled: bool | None = None) -> FastAPI:
    """アプリケーションを生成する。

    map_pathを外部から渡せるようにし、テストでは本番用地図に依存しない構成にする。
    """
    application = FastAPI(title="屋内経路探索API", version="1.0.0")
    # 本番アプリとは別ポートで動かすローカル検証画面からのAPI呼び出しだけを許可する。
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8080", "http://localhost:8080"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    # 現段階ではDBを使わず、プロセス内のリポジトリとして状態を保持する。
    application.state.map_repository = JsonMapRepository(map_path or DEFAULT_MAP_PATH)
    application.state.positions = PositionRepository()
    application.state.obstacles = ObstacleRepository()
    application.state.sessions = NavigationSessionRepository()
    application.state.communication_logs = CommunicationLogRepository(max_entries=100)
    application.state.navigation = NavigationSessionService(
        application.state.map_repository, application.state.positions,
        application.state.obstacles, application.state.sessions,
    )
    application.state.dev_panel = DevPanelService(
        application.state.map_repository, application.state.positions, application.state.sessions,
        application.state.obstacles, application.state.communication_logs,
    )
    application.include_router(router)
    application.include_router(navigation_router)
    if _dev_panel_enabled(dev_panel_enabled):
        application.add_middleware(DevelopmentCommunicationMiddleware)
        application.include_router(dev_router)

    @application.exception_handler(MapDataError)
    async def map_data_error_handler(request: Request, exc: MapDataError) -> JSONResponse:
        # 利用者には内部情報を公開せず、詳しい原因はサーバーログへ記録する。
        logger.exception("Map data could not be loaded for %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": {"code": "MAP_DATA_ERROR", "message": "地図データを読み込めません"}},
        )

    @application.get("/", include_in_schema=False)
    async def read_root() -> dict[str, str]:
        return {"message": "Indoor Navigation API", "docs": "/docs"}

    return application


app = create_app()
