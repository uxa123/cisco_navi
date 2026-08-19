"""開発パネル画面と読み取り専用の集約状態API。"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.schemas.dev import (
    DevMockPayloadRequest, DevMockPayloadResponse, DevMockRouteResponse,
    DevResetResponse, DevStatusResponse,
)

router = APIRouter(include_in_schema=False)
ASSET_DIR = Path(__file__).resolve().parent.parent / "dev_static"
NO_CACHE_HEADERS = {"Cache-Control": "no-store, max-age=0"}


@router.get("/dev")
async def development_panel() -> HTMLResponse:
    return HTMLResponse(
        (ASSET_DIR / "index.html").read_text(encoding="utf-8"),
        headers=NO_CACHE_HEADERS,
    )


@router.get("/dev/assets/dev.css")
async def development_styles() -> Response:
    return Response(
        (ASSET_DIR / "dev.css").read_text(encoding="utf-8"),
        media_type="text/css", headers=NO_CACHE_HEADERS,
    )


@router.get("/dev/assets/dev.js")
async def development_script() -> Response:
    return Response(
        (ASSET_DIR / "dev.js").read_text(encoding="utf-8"),
        media_type="text/javascript", headers=NO_CACHE_HEADERS,
    )


@router.get("/api/dev/status", response_model=DevStatusResponse)
async def development_status(request: Request) -> DevStatusResponse:
    return request.app.state.dev_panel.status()


@router.get("/api/dev/mock/route", response_model=DevMockRouteResponse)
async def development_mock_route(request: Request) -> DevMockRouteResponse:
    return request.app.state.dev_panel.mock_route()


@router.post("/api/dev/mock/payload", response_model=DevMockPayloadResponse)
async def development_mock_payload(
    body: DevMockPayloadRequest, request: Request,
) -> DevMockPayloadResponse:
    return request.app.state.dev_panel.mock_payload(body)


@router.post("/api/dev/reset", response_model=DevResetResponse)
async def reset_development_state(request: Request) -> DevResetResponse:
    request.app.state.dev_panel.reset()
    return DevResetResponse(message="開発用メモリ状態をリセットしました")
