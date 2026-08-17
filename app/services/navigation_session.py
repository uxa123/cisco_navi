"""ナビゲーションセッションのライフサイクルと状態更新。"""

import math
from datetime import datetime, timezone
from uuid import uuid4

from app.repositories import JsonMapRepository, NavigationSessionRepository, ObstacleRepository, PositionRepository
from app.schemas.models import (
    FloorMap, MovementRequest, NavigationCurrentPosition, NavigationGuidance,
    NavigationSession, NavigationPoint, NormalizedPosition, RouteNode,
)
from app.services.map_matching import MapMatchingService
from app.services.navigation import NavigationService, RouteNotFoundError, find_nearest_node
from app.services.pdr import PdrService
from app.services.position_fusion import PositionFusionService

OFF_ROUTE_TOLERANCE_M = 2.0
ARRIVAL_TOLERANCE_M = 1.0


class SessionNotFoundError(LookupError):
    pass


class SessionInactiveError(RuntimeError):
    pass


class PositionNotFoundError(LookupError):
    pass


class DestinationNotFoundError(LookupError):
    pass


class InvalidMovementError(ValueError):
    pass


class NavigationSessionService:
    def __init__(
        self, maps: JsonMapRepository, positions: PositionRepository,
        obstacles: ObstacleRepository, sessions: NavigationSessionRepository,
    ) -> None:
        self.maps = maps
        self.positions = positions
        self.obstacles = obstacles
        self.sessions = sessions
        self.matcher = MapMatchingService()
        self.pdr = PdrService()
        self.fusion = PositionFusionService()
        self.routes = NavigationService()

    def create(self, client_id: str, destination_id: str) -> NavigationSession:
        absolute = self.positions.get_latest(client_id)
        if absolute is None:
            raise PositionNotFoundError
        floor = self.maps.get_floor(absolute.floor_id)
        if floor is None:
            raise PositionNotFoundError
        if not any(node.id == destination_id for node in floor.nodes):
            raise DestinationNotFoundError
        now = datetime.now(timezone.utc)
        fused = self.fusion.initialize(absolute)
        current = self._current_position(floor, fused.fused_position)
        route, edges, distance, guidance = self._plan(floor, current, destination_id)
        session = NavigationSession(
            session_id=f"nav-{uuid4().hex[:12]}", client_id=client_id,
            destination_id=destination_id, current_position=current,
            current_route=route, route_edge_ids=edges,
            remaining_distance_m=distance, next_guidance=guidance,
            position_state=fused, created_at=now, updated_at=now,
        )
        session = self._update(session, fused)
        self.sessions.save(session)
        return session

    def get(self, session_id: str) -> NavigationSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError
        return session

    def finish(self, session_id: str) -> NavigationSession:
        session = self.get(session_id)
        if session.status == "active":
            session = session.model_copy(update={
                "status": "finished", "updated_at": datetime.now(timezone.utc),
            })
            self.sessions.save(session)
        return session

    def movement(self, session_id: str, movement: MovementRequest) -> tuple[NavigationSession, bool]:
        session = self.get(session_id)
        if session.status != "active":
            raise SessionInactiveError
        if session.last_sequence is not None and movement.sequence <= session.last_sequence:
            return session, True
        try:
            origin = session.position_state.pdr_position or session.position_state.fused_position
            pdr_position = self.pdr.apply(origin, movement)
        except ValueError as exc:
            raise InvalidMovementError(str(exc)) from exc
        fused = self.fusion.apply_pdr(session.position_state, pdr_position)
        updated = self._update(session, fused)
        updated = updated.model_copy(update={"last_sequence": movement.sequence})
        self.sessions.save(updated)
        return updated, False

    def correct_client(self, position: NormalizedPosition) -> None:
        for session in self.sessions.active_for_client(position.client_id):
            if session.current_position.floor_id != position.floor_id:
                continue
            fused = self.fusion.correct_with_meraki(session.position_state, position)
            self.sessions.save(self._update(session, fused))

    def obstacle_changed(self, edge_id: str, blocked: bool) -> None:
        if not blocked:
            return
        for session in self.sessions.list():
            if session.status == "active" and edge_id in session.route_edge_ids:
                try:
                    self.sessions.save(self._update(session, session.position_state, force_replan=True))
                except RouteNotFoundError:
                    # 通行止めAPI自体の互換性を保ち、経路ができるまで現ルートを保持する。
                    continue

    def _current_position(self, floor: FloorMap, position: NavigationPoint) -> NavigationCurrentPosition:
        result = self.matcher.match(floor, position)
        point = result.matched_position
        return NavigationCurrentPosition(
            floor_id=point.floor_id, x=point.x, y=point.y, source=position.source,
            matched_edge=result.edge, raw_x=position.x, raw_y=position.y,
            distance_from_edge_m=result.distance_from_edge_m,
        )

    def _plan(
        self, floor: FloorMap, current: NavigationCurrentPosition, destination_id: str,
    ) -> tuple[list[RouteNode], list[str], float, NavigationGuidance]:
        start, offset = find_nearest_node(floor, current.x, current.y)
        nodes, distance, guidance = self.routes.search(
            floor, start.id, destination_id, self.obstacles.blocked_edge_ids()
        )
        route = [RouteNode(id=node.id, name=node.name, x=node.x, y=node.y) for node in nodes]
        edge_ids = self._route_edges(floor, [node.id for node in nodes])
        first = guidance[0]
        next_guidance = NavigationGuidance(
            action=first.type, distance_m=round(first.distance + offset, 2), message=first.message,
        )
        return route, edge_ids, round(distance + offset, 2), next_guidance

    @staticmethod
    def _route_edges(floor: FloorMap, node_ids: list[str]) -> list[str]:
        result = []
        for left, right in zip(node_ids, node_ids[1:]):
            edge = next((item for item in floor.edges if
                         (item.from_node == left and item.to == right) or
                         (item.bidirectional and item.from_node == right and item.to == left)), None)
            if edge:
                result.append(edge.id)
        return result

    @staticmethod
    def _distance_to_route(current: NavigationCurrentPosition, route: list[RouteNode]) -> float:
        if len(route) < 2:
            return math.hypot(current.x - route[0].x, current.y - route[0].y) if route else math.inf
        return min(MapMatchingService.project(current.x, current.y, a.x, a.y, b.x, b.y)[2]
                   for a, b in zip(route, route[1:]))

    @staticmethod
    def _remaining_on_route(current: NavigationCurrentPosition, route: list[RouteNode]) -> tuple[float, float]:
        if len(route) < 2:
            return 0.0, 0.0
        best = None
        suffix = [0.0] * len(route)
        for index in range(len(route) - 2, -1, -1):
            suffix[index] = suffix[index + 1] + math.hypot(
                route[index + 1].x - route[index].x, route[index + 1].y - route[index].y)
        for index, (a, b) in enumerate(zip(route, route[1:])):
            x, y, distance = MapMatchingService.project(current.x, current.y, a.x, a.y, b.x, b.y)
            remaining_segment = math.hypot(b.x - x, b.y - y)
            candidate = (distance, remaining_segment + suffix[index + 1], remaining_segment)
            if best is None or candidate[0] < best[0]:
                best = candidate
        return best[1], best[2]

    def _update(self, session, fused, force_replan: bool = False) -> NavigationSession:
        floor = self.maps.get_floor(fused.fused_position.floor_id)
        if floor is None:
            return session
        current = self._current_position(floor, fused.fused_position)
        destination = next(node for node in floor.nodes if node.id == session.destination_id)
        if math.hypot(current.x - destination.x, current.y - destination.y) <= ARRIVAL_TOLERANCE_M:
            now = datetime.now(timezone.utc)
            return session.model_copy(update={
                "status": "arrived", "current_position": current, "position_state": fused,
                "remaining_distance_m": 0.0,
                "next_guidance": NavigationGuidance(action="arrive", distance_m=0, message="目的地に到着しました"),
                "route_changed": False, "updated_at": now,
            })
        off_route = self._distance_to_route(current, session.current_route) > OFF_ROUTE_TOLERANCE_M
        if force_replan or off_route:
            route, edges, distance, guidance = self._plan(floor, current, session.destination_id)
            return session.model_copy(update={
                "current_position": current, "position_state": fused, "current_route": route,
                "route_edge_ids": edges, "remaining_distance_m": distance,
                "next_guidance": guidance, "route_changed": True,
                "updated_at": datetime.now(timezone.utc),
            })
        remaining, next_distance = self._remaining_on_route(current, session.current_route)
        guidance = NavigationGuidance(
            action="straight", distance_m=round(next_distance, 2),
            message=f"{round(next_distance, 2):g}メートル直進してください",
        )
        return session.model_copy(update={
            "current_position": current, "position_state": fused,
            "remaining_distance_m": round(remaining, 2), "next_guidance": guidance,
            "route_changed": False, "updated_at": datetime.now(timezone.utc),
        })
