"""実機接続前のAPI連携確認に使用するScanning API v3モック生成処理。"""

import json
import math
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class MockDataError(ValueError):
    """経路またはAP配置データが不正な場合の例外。"""


class RoutePosition(BaseModel):
    x: float
    y: float
    wait_seconds: float = Field(default=2, ge=0)


class MockRoute(BaseModel):
    floor_plan_id: str = Field(alias="floorPlanId")
    floor_plan_name: str = Field(alias="floorPlanName")
    positions: list[RoutePosition] = Field(min_length=1)

    model_config = {"populate_by_name": True}


class AccessPoint(BaseModel):
    mac: str
    name: str
    x: float
    y: float


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MockDataError(f"JSONファイルを読み込めません: {path}: {exc}") from exc


def load_route(path: Path) -> MockRoute:
    """移動経路JSONを読み込み、必須項目を検証する。"""
    try:
        return MockRoute.model_validate(_read_json(path))
    except ValidationError as exc:
        raise MockDataError(f"経路ファイルの形式が不正です: {path}: {exc}") from exc


def load_access_points(path: Path) -> list[AccessPoint]:
    """AP配置JSONを読み込み、少なくとも1台存在することを検証する。"""
    try:
        access_points = [AccessPoint.model_validate(item) for item in _read_json(path)]
    except (TypeError, ValidationError) as exc:
        raise MockDataError(f"AP位置ファイルの形式が不正です: {path}: {exc}") from exc
    if not access_points:
        raise MockDataError(f"AP位置ファイルにAPがありません: {path}")
    return access_points


class ScanningMockService:
    """座標とAP配置から再現可能なWi-Fi Payloadを生成する。"""

    def __init__(self, access_points: list[AccessPoint], seed: int | None = None) -> None:
        if not access_points:
            raise MockDataError("APを1台以上指定してください")
        self.access_points = access_points
        self.random = random.Random(seed)

    def _rssi_records(self, x: float, y: float) -> list[dict[str, int | str]]:
        records: list[dict[str, int | str]] = []
        for ap in self.access_points:
            distance = math.hypot(x - ap.x, y - ap.y)
            # 簡易モデルのため、距離1mごとに約2dB減衰し小さな乱数誤差を加える。
            rssi = round(max(-95, min(-30, -35 - distance * 2 + self.random.uniform(-2, 2))))
            records.append({"apMac": ap.mac, "rssi": rssi})
        return records

    def build_payload(
        self,
        *,
        route: MockRoute,
        position: RoutePosition,
        observed_at: datetime,
        client_mac: str,
        network_id: str,
        secret: str,
        scenario: str = "normal",
    ) -> dict[str, Any]:
        """指定位置からMeraki Wi-Fi Payloadに近い辞書を生成する。"""
        x, y, variance = position.x, position.y, 1.5
        if scenario == "noisy":
            x += self.random.uniform(-1, 1)
            y += self.random.uniform(-1, 1)
            variance = round(self.random.uniform(1.5, 4.0), 2)
        rssi_records = self._rssi_records(x, y)
        nearest = max(rssi_records, key=lambda item: int(item["rssi"]))
        timestamp = observed_at.isoformat()
        locations: list[dict[str, Any]] = []
        if scenario != "location-unavailable":
            locations.append({
                # 公式Payload例に合わせ、座標は数値ではなく文字列として送信する。
                "x": str(round(x, 2)), "y": str(round(y, 2)),
                "floorPlanId": route.floor_plan_id, "floorPlanName": route.floor_plan_name,
                "time": timestamp, "variance": variance, "rssiRecords": rssi_records,
            })
        return {
            "version": "3.0", "secret": secret, "type": "WiFi",
            "data": {"networkId": network_id, "observations": [{
                "clientMac": client_mac, "manufacturer": "Mock Device", "ssid": "D1-Navigation",
                "locations": locations,
                "latestRecord": {
                    "time": timestamp, "nearestApMac": nearest["apMac"],
                    "nearestApRssi": str(nearest["rssi"]),
                },
            }]},
        }
