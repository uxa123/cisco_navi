"""推定座標を最寄りの通路線分へ投影する。"""

import math

from app.schemas.models import FloorMap, MapMatchResult, MatchedEdge, NavigationPoint


class MapMatchingService:
    def __init__(self, max_distance_m: float = 3.0) -> None:
        self.max_distance_m = max_distance_m

    @staticmethod
    def project(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float, float]:
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            return ax, ay, math.hypot(px - ax, py - ay)
        ratio = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
        x, y = ax + ratio * dx, ay + ratio * dy
        return x, y, math.hypot(px - x, py - y)

    def match(self, floor: FloorMap, position: NavigationPoint) -> MapMatchResult:
        nodes = {node.id: node for node in floor.nodes}
        best = None
        for edge in floor.edges:
            start, end = nodes.get(edge.from_node), nodes.get(edge.to)
            if start is None or end is None:
                continue
            x, y, distance = self.project(position.x, position.y, start.x, start.y, end.x, end.y)
            if best is None or distance < best[0]:
                best = (distance, x, y, edge)
        if best is None or best[0] > self.max_distance_m:
            return MapMatchResult(
                raw_position=position, matched_position=position, matched=False,
                distance_from_edge_m=None if best is None else round(best[0], 3),
            )
        distance, x, y, edge = best
        matched = position.model_copy(update={"x": x, "y": y, "source": "map_matched"})
        return MapMatchResult(
            raw_position=position, matched_position=matched, matched=True,
            edge=MatchedEdge(id=edge.id, from_node=edge.from_node, to=edge.to),
            distance_from_edge_m=round(distance, 3),
        )
