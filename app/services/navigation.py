"""最寄りノード判定、経路探索、案内生成のビジネスロジック。"""

import math

import networkx as nx

from app.schemas.models import FloorMap, GuidanceStep, MapNode


class RouteNotFoundError(RuntimeError):
    """通行可能な経路が存在しない場合の例外。"""


def absolute_heading_deg(x: float, y: float, target_x: float, target_y: float) -> float | None:
    """現在座標から目標座標への絶対方位を0°=北、90°=東で返す。"""
    dx, dy = target_x - x, target_y - y
    if math.hypot(dx, dy) < 1e-6:
        return None
    return round(math.degrees(math.atan2(dx, dy)) % 360, 2)


def segment_action(route: list[MapNode], index: int) -> str:
    """経路の指定セグメントへ進入するときの案内種別を返す。"""
    if index <= 0:
        return "straight"
    previous, current, following = route[index - 1], route[index], route[index + 1]
    ax, ay = current.x - previous.x, current.y - previous.y
    bx, by = following.x - current.x, following.y - current.y
    cross = ax * by - ay * bx
    dot = ax * bx + ay * by
    angle = math.degrees(math.atan2(abs(cross), dot))
    if angle < 30:
        return "straight"
    return "left" if cross > 0 else "right"


def guidance_step(action: str, distance: float) -> GuidanceStep:
    messages = {
        "straight": f"{distance:g}メートル直進してください",
        "left": f"左折して{distance:g}メートル進んでください",
        "right": f"右折して{distance:g}メートル進んでください",
    }
    return GuidanceStep(type=action, distance=distance, message=messages[action])


def find_nearest_node(floor_map: FloorMap, x: float, y: float) -> tuple[MapNode, float]:
    """指定座標からユークリッド距離が最小となるノードを返す。"""
    if not floor_map.nodes:
        raise RouteNotFoundError("Map has no nodes")
    node = min(floor_map.nodes, key=lambda item: math.hypot(item.x - x, item.y - y))
    return node, math.hypot(node.x - x, node.y - y)


class NavigationService:
    """通行止めエッジを除外し、同一フロア内の最短経路を探索する。"""

    def search(
        self, floor_map: FloorMap, start_id: str, destination_id: str, blocked: set[str]
    ) -> tuple[list[MapNode], float, list[GuidanceStep]]:
        nodes = {node.id: node for node in floor_map.nodes}
        graph = nx.DiGraph()
        graph.add_nodes_from(nodes)
        for edge in floor_map.edges:
            # グラフへ追加しないことで、通行止めを経路探索の候補から除外する。
            if edge.id in blocked:
                continue
            graph.add_edge(edge.from_node, edge.to, weight=edge.distance, edge_id=edge.id)
            if edge.bidirectional:
                # 双方向通路は逆向きのエッジも登録する。
                graph.add_edge(edge.to, edge.from_node, weight=edge.distance, edge_id=edge.id)
        try:
            ids = nx.shortest_path(graph, start_id, destination_id, weight="weight")
            distance = nx.shortest_path_length(graph, start_id, destination_id, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            raise RouteNotFoundError from exc
        route = [nodes[node_id] for node_id in ids]
        return route, round(float(distance), 2), self._guidance(route, graph)

    @staticmethod
    def _guidance(route: list[MapNode], graph: nx.DiGraph) -> list[GuidanceStep]:
        """経路上の座標変化から簡易的な案内文を生成する。"""
        if len(route) == 1:
            return [GuidanceStep(type="arrive", distance=0, message="目的地に到着しました")]
        result: list[GuidanceStep] = []
        for index in range(len(route) - 1):
            current, following = route[index], route[index + 1]
            distance = round(float(graph[current.id][following.id]["weight"]), 2)
            result.append(guidance_step(segment_action(route, index), distance))
        result.append(GuidanceStep(type="arrive", distance=0, message="目的地に到着しました"))
        return result
