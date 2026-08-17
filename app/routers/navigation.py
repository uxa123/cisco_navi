"""ナビゲーションセッションREST API。"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.schemas.models import (
    MovementRequest, MovementResponse, NavigationSessionCreateRequest,
    NavigationSessionResponse, NavigationStateResponse,
)
from app.services.navigation import RouteNotFoundError
from app.services.navigation_session import (
    DestinationNotFoundError, InvalidMovementError, NavigationSessionService,
    PositionNotFoundError, SessionInactiveError, SessionNotFoundError,
)

router = APIRouter(prefix="/api/navigation/sessions")


async def get_service(request: Request) -> NavigationSessionService:
    return request.app.state.navigation


def error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def session_response(session) -> NavigationSessionResponse:
    return NavigationSessionResponse(
        session_id=session.session_id, client_id=session.client_id,
        destination_id=session.destination_id, status=session.status,
        route=session.current_route, remaining_distance_m=session.remaining_distance_m,
        next_guidance=session.next_guidance, current_position=session.current_position,
        created_at=session.created_at, updated_at=session.updated_at,
    )


def state_response(session) -> NavigationStateResponse:
    return NavigationStateResponse(
        session_id=session.session_id, status=session.status,
        current_position=session.current_position, destination_id=session.destination_id,
        remaining_distance_m=session.remaining_distance_m,
        next_guidance=session.next_guidance, route_changed=session.route_changed,
        updated_at=session.updated_at, position_state=session.position_state,
    )


@router.post("", response_model=NavigationSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: NavigationSessionCreateRequest, service: NavigationSessionService = Depends(get_service),
) -> NavigationSessionResponse:
    try:
        return session_response(service.create(body.client_id, body.destination_id))
    except PositionNotFoundError as exc:
        raise error(404, "POSITION_NOT_FOUND", "利用者の位置情報が見つかりません") from exc
    except DestinationNotFoundError as exc:
        raise error(404, "DESTINATION_NOT_FOUND", "目的地ノードが見つかりません") from exc
    except RouteNotFoundError as exc:
        raise error(409, "ROUTE_NOT_FOUND", "目的地までの経路が見つかりません") from exc


@router.get("/{session_id}", response_model=NavigationSessionResponse)
async def get_session(
    session_id: str, service: NavigationSessionService = Depends(get_service),
) -> NavigationSessionResponse:
    try:
        return session_response(service.get(session_id))
    except SessionNotFoundError as exc:
        raise error(404, "SESSION_NOT_FOUND", "ナビゲーションセッションが見つかりません") from exc


@router.get("/{session_id}/state", response_model=NavigationStateResponse)
async def get_state(
    session_id: str, service: NavigationSessionService = Depends(get_service),
) -> NavigationStateResponse:
    try:
        return state_response(service.get(session_id))
    except SessionNotFoundError as exc:
        raise error(404, "SESSION_NOT_FOUND", "ナビゲーションセッションが見つかりません") from exc


@router.delete("/{session_id}", response_model=NavigationSessionResponse)
async def finish_session(
    session_id: str, service: NavigationSessionService = Depends(get_service),
) -> NavigationSessionResponse:
    try:
        return session_response(service.finish(session_id))
    except SessionNotFoundError as exc:
        raise error(404, "SESSION_NOT_FOUND", "ナビゲーションセッションが見つかりません") from exc


@router.post("/{session_id}/movements", response_model=MovementResponse)
async def receive_movement(
    session_id: str, body: MovementRequest,
    service: NavigationSessionService = Depends(get_service),
) -> MovementResponse:
    try:
        session, duplicate = service.movement(session_id, body)
        return MovementResponse(
            **state_response(session).model_dump(), sequence=body.sequence, duplicate=duplicate,
        )
    except SessionNotFoundError as exc:
        raise error(404, "SESSION_NOT_FOUND", "ナビゲーションセッションが見つかりません") from exc
    except SessionInactiveError as exc:
        raise error(409, "SESSION_INACTIVE", "終了済みのセッションは更新できません") from exc
    except InvalidMovementError as exc:
        raise error(422, "INVALID_MOVEMENT", str(exc)) from exc
    except RouteNotFoundError as exc:
        raise error(409, "ROUTE_NOT_FOUND", "目的地までの経路が見つかりません") from exc
