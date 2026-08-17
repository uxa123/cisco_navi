"""最寄りノード判定、経路探索、案内生成のビジネスロジック。"""

import math

import networkx as nx

from app.schemas.models import FloorMap, GuidanceStep, MapNode


class RouteNotFoundError(RuntimeError):
    """通行可能な経路が存在しない場合の例外。"""


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
            turn = "straight"
            if index > 0:
                previous = route[index - 1]
                # 進入ベクトルと退出ベクトルの外積の符号で左右を判定する。
                ax, ay = current.x - previous.x, current.y - previous.y
                bx, by = following.x - current.x, following.y - current.y
                cross = ax * by - ay * bx
                dot = ax * bx + ay * by
                angle = math.degrees(math.atan2(abs(cross), dot))
                # 小さな方向変化は測量誤差を考慮し、直進として扱う。
                if angle >= 30:
                    turn = "left" if cross > 0 else "right"
            messages = {
                "straight": f"{distance:g}メートル直進してください",
                "left": f"左折して{distance:g}メートル進んでください",
                "right": f"右折して{distance:g}メートル進んでください",
            }
            result.append(GuidanceStep(type=turn, distance=distance, message=messages[turn]))
        result.append(GuidanceStep(type="arrive", distance=0, message="目的地に到着しました"))
        return result
