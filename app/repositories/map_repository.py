"""JSONファイルを利用する施設地図リポジトリ。"""

import json
from pathlib import Path

from pydantic import ValidationError

from app.schemas.models import FloorMap, MapEdge


class MapDataError(RuntimeError):
    """地図データの読み込みまたは検証に失敗した場合の例外。"""


class JsonMapRepository:
    """保存方式を呼び出し側へ公開せず、JSONファイルから地図を取得する。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> list[FloorMap]:
        try:
            # PydanticでJSONの構造と各フィールドを同時に検証する。
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [FloorMap.model_validate(item) for item in raw["floors"]]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
            raise MapDataError(f"Failed to load map data from {self.path}: {exc}") from exc

    def get_floor(self, floor_id: str) -> FloorMap | None:
        return next((floor for floor in self._load() if floor.floor_id == floor_id), None)

    def find_edge(self, edge_id: str) -> tuple[FloorMap, MapEdge] | None:
        """全フロアから指定されたエッジを検索する。"""
        for floor in self._load():
            for edge in floor.edges:
                if edge.id == edge_id:
                    return floor, edge
        return None
