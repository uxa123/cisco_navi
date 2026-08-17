"""屋内ナビゲーションAPIのHTTPエンドポイント。"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.repositories import JsonMapRepository, ObstacleRepository, PositionRepository
from app.schemas.models import (
    FloorMap, MockPositionRequest, NearestNode, NormalizedPosition, Obstacle,
    ObstacleRequest, ObstacleResponse, PositionCoordinates, PositionResponse,
    RouteEndpoint, RouteNode, RouteResponse, RouteSearchRequest,
    ScanningPayload, ScanningReceiveResponse,
)
from app.services.navigation import NavigationService, RouteNotFoundError, find_nearest_node
from app.services.scanning import normalize_observation

router = APIRouter(prefix="/api")


def _error(status_code: int, code: str, message: str) -> HTTPException:
    """API独自エラーを共通形式で生成する。"""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def get_map_repository(request: Request) -> JsonMapRepository:
    return request.app.state.map_repository


async def get_positions(request: Request) -> PositionRepository:
    return request.app.state.positions


async def get_obstacles(request: Request) -> ObstacleRepository:
    return request.app.state.obstacles


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/scanning", response_model=ScanningReceiveResponse)
async def receive_scanning_payload(
    body: ScanningPayload,
    request: Request,
    maps: JsonMapRepository = Depends(get_map_repository),
    positions: PositionRepository = Depends(get_positions),
) -> ScanningReceiveResponse:
    """Meraki Scanning API v3形式のWi-Fi位置情報を受信する。"""
    updated_clients: list[str] = []
    skipped = 0
    for observation in body.data.observations:
        normalized = normalize_observation(observation)
        if normalized is None:
            skipped += 1
            continue
        # 未知のfloorPlanIdは保存せず、送信側が誤りに気づけるよう404を返す。
        if maps.get_floor(normalized.floor_id) is None:
            raise _error(404, "MAP_NOT_FOUND", "受信した位置に対応する地図が見つかりません")
        positions.save(normalized)
        request.app.state.navigation.correct_client(normalized)
        updated_clients.append(normalized.client_id)
    return ScanningReceiveResponse(
        received=len(body.data.observations), updated=len(updated_clients),
        skipped=skipped, client_ids=updated_clients,
    )


@router.get("/maps/{floor_id}", response_model=FloorMap, response_model_by_alias=True)
async def get_map(floor_id: str, maps: JsonMapRepository = Depends(get_map_repository)) -> FloorMap:
    floor = maps.get_floor(floor_id)
    if floor is None:
        raise _error(404, "MAP_NOT_FOUND", "指定された地図が見つかりません")
    return floor


def _position_response(position: NormalizedPosition, floor: FloorMap) -> PositionResponse:
    """正規化済み位置から最寄りノードを含むレスポンスを作成する。"""
    nearest, distance = find_nearest_node(floor, position.x, position.y)
    return PositionResponse(
        client_id=position.client_id,
        position=PositionCoordinates(floor_id=position.floor_id, x=position.x, y=position.y),
        nearest_node=NearestNode(id=nearest.id, name=nearest.name, distance=round(distance, 2)),
        variance=position.variance, observed_at=position.observed_at, source=position.source,
    )


@router.post("/mock/positions", response_model=PositionResponse)
async def register_mock_position(
    body: MockPositionRequest,
    maps: JsonMapRepository = Depends(get_map_repository),
    positions: PositionRepository = Depends(get_positions),
) -> PositionResponse:
    floor = maps.get_floor(body.floor_id)
    if floor is None:
        raise _error(404, "MAP_NOT_FOUND", "指定された地図が見つかりません")
    # 将来Meraki入力を追加しても、保存後は同じNormalizedPositionとして扱う。
    normalized = NormalizedPosition(**body.model_dump(), source="mock")
    positions.save(normalized)
    return _position_response(normalized, floor)


@router.get("/positions/{client_id}", response_model=PositionResponse)
async def latest_position(
    client_id: str,
    maps: JsonMapRepository = Depends(get_map_repository),
    positions: PositionRepository = Depends(get_positions),
) -> PositionResponse:
    position = positions.get_latest(client_id)
    if position is None:
        raise _error(404, "POSITION_NOT_FOUND", "利用者の位置情報が見つかりません")
    floor = maps.get_floor(position.floor_id)
    if floor is None:
        raise _error(404, "MAP_NOT_FOUND", "指定された地図が見つかりません")
    return _position_response(position, floor)


@router.post("/routes/search", response_model=RouteResponse)
async def search_route(
    body: RouteSearchRequest,
    maps: JsonMapRepository = Depends(get_map_repository),
    positions: PositionRepository = Depends(get_positions),
    obstacles: ObstacleRepository = Depends(get_obstacles),
) -> RouteResponse:
    position = positions.get_latest(body.client_id)
    if position is None:
        raise _error(404, "POSITION_NOT_FOUND", "利用者の位置情報が見つかりません")
    floor = maps.get_floor(position.floor_id)
    if floor is None:
        raise _error(404, "MAP_NOT_FOUND", "指定された地図が見つかりません")
    destination = next((node for node in floor.nodes if node.id == body.destination_node_id), None)
    if destination is None:
        raise _error(404, "DESTINATION_NOT_FOUND", "目的地ノードが見つかりません")
    start, _ = find_nearest_node(floor, position.x, position.y)
    try:
        # ルーターは入出力に専念し、経路計算はサービスへ委譲する。
        route, distance, guidance = NavigationService().search(
            floor, start.id, destination.id, obstacles.blocked_edge_ids()
        )
    except RouteNotFoundError as exc:
        raise _error(status.HTTP_409_CONFLICT, "ROUTE_NOT_FOUND", "目的地までの経路が見つかりません") from exc
    return RouteResponse(
        client_id=body.client_id, floor_id=floor.floor_id,
        start_node=RouteEndpoint(id=start.id, name=start.name),
        destination_node=RouteEndpoint(id=destination.id, name=destination.name),
        total_distance=distance,
        route=[RouteNode(id=node.id, name=node.name, x=node.x, y=node.y) for node in route],
        guidance=guidance,
    )


@router.post("/obstacles", response_model=ObstacleResponse)
async def set_obstacle(
    body: ObstacleRequest,
    request: Request,
    maps: JsonMapRepository = Depends(get_map_repository),
    obstacles: ObstacleRepository = Depends(get_obstacles),
) -> ObstacleResponse:
    if maps.find_edge(body.edge_id) is None:
        raise _error(404, "EDGE_NOT_FOUND", "指定されたエッジが見つかりません")
    obstacle = Obstacle(**body.model_dump())
    obstacles.save(obstacle)
    request.app.state.navigation.obstacle_changed(body.edge_id, body.blocked)
    message = "通路を通行不可に設定しました" if body.blocked else "通路の通行止めを解除しました"
    return ObstacleResponse(**obstacle.model_dump(), message=message)


@router.get("/obstacles", response_model=list[Obstacle])
async def list_obstacles(obstacles: ObstacleRepository = Depends(get_obstacles)) -> list[Obstacle]:
    return obstacles.list()
