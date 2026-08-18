"""開発時のHTTP通信メタデータ収集。"""

from datetime import datetime, timezone
from time import perf_counter

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.schemas.dev import CommunicationLog
from app.services.dev_panel import classify_source, session_id_from_path


class DevelopmentCommunicationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            path = request.url.path
            # リセット要求自身を残すと、リセット直後にログが1件復活するため記録しない。
            if path != "/api/dev/reset":
                session_id = session_id_from_path(path)
                session = request.app.state.sessions.get(session_id) if session_id else None
                request.app.state.communication_logs.save(CommunicationLog(
                    timestamp=datetime.now(timezone.utc), method=request.method,
                    path=path, status_code=status_code,
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                    source=classify_source(path), client_id=session.client_id if session else None,
                    session_id=session_id,
                ))
