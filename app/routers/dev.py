"""開発パネル画面と読み取り専用の集約状態API。"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.schemas.dev import DevResetResponse, DevStatusResponse

router = APIRouter(include_in_schema=False)
ASSET_DIR = Path(__file__).resolve().parent.parent / "dev_static"
PANEL_HTML = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
PANEL_CSS = (ASSET_DIR / "dev.css").read_text(encoding="utf-8")
PANEL_JS = (ASSET_DIR / "dev.js").read_text(encoding="utf-8")


@router.get("/dev")
async def development_panel() -> HTMLResponse:
    return HTMLResponse(PANEL_HTML)


@router.get("/dev/assets/dev.css")
async def development_styles() -> Response:
    return Response(PANEL_CSS, media_type="text/css")


@router.get("/dev/assets/dev.js")
async def development_script() -> Response:
    return Response(PANEL_JS, media_type="text/javascript")


@router.get("/api/dev/status", response_model=DevStatusResponse)
async def development_status(request: Request) -> DevStatusResponse:
    return request.app.state.dev_panel.status()


@router.post("/api/dev/reset", response_model=DevResetResponse)
async def reset_development_state(request: Request) -> DevResetResponse:
    request.app.state.dev_panel.reset()
    return DevResetResponse(message="開発用メモリ状態をリセットしました")
