"""リクエスト、レスポンス、および地図データのモデル定義。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MapNode(BaseModel):
    id: str
    name: str
    floor_id: str
    x: float
    y: float
    type: str


class MapEdge(BaseModel):
    id: str
    from_node: str = Field(alias="from", serialization_alias="from")
    to: str
    distance: float = Field(gt=0)
    bidirectional: bool = True

    model_config = {"populate_by_name": True}


class FloorMap(BaseModel):
    floor_id: str
    name: str
    nodes: list[MapNode]
    edges: list[MapEdge]


class MockPositionRequest(BaseModel):
    client_id: str = Field(min_length=1)
    floor_id: str
    x: float
    y: float
    variance: float | None = Field(default=None, ge=0)
    observed_at: datetime


class NormalizedPosition(BaseModel):
    """モック入力と将来のMeraki入力で共用する正規化済み位置形式。"""

    client_id: str
    floor_id: str
    x: float
    y: float
    variance: float | None = None
    observed_at: datetime
    source: str


class PositionCoordinates(BaseModel):
    floor_id: str
    x: float
    y: float


class NearestNode(BaseModel):
    id: str
    name: str
    distance: float


class PositionResponse(BaseModel):
    client_id: str
    position: PositionCoordinates
    nearest_node: NearestNode
    variance: float | None = None
    observed_at: datetime
    source: str


class RouteSearchRequest(BaseModel):
    client_id: str = Field(min_length=1)
    destination_node_id: str


class RouteEndpoint(BaseModel):
    id: str
    name: str


class RouteNode(RouteEndpoint):
    x: float
    y: float


class GuidanceStep(BaseModel):
    type: Literal["straight", "right", "left", "arrive"]
    distance: float
    message: str


class RouteResponse(BaseModel):
    client_id: str
    floor_id: str
    start_node: RouteEndpoint
    destination_node: RouteEndpoint
    total_distance: float
    route: list[RouteNode]
    guidance: list[GuidanceStep]


class ObstacleRequest(BaseModel):
    edge_id: str
    blocked: bool
    reason: str | None = None
    source: str = "mock"


class Obstacle(BaseModel):
    edge_id: str
    blocked: bool
    reason: str | None = None
    source: str


class ObstacleResponse(Obstacle):
    message: str


# Meraki Scanning API v3のJSONキーはcamelCaseのため、aliasでPython側の名前と対応させる。
class RssiRecord(BaseModel):
    ap_mac: str = Field(alias="apMac", serialization_alias="apMac")
    rssi: int

    model_config = {"populate_by_name": True}


class ScanningLocation(BaseModel):
    x: str
    y: str
    floor_plan_id: str = Field(alias="floorPlanId", serialization_alias="floorPlanId")
    floor_plan_name: str | None = Field(default=None, alias="floorPlanName", serialization_alias="floorPlanName")
    time: datetime
    variance: float | None = None
    rssi_records: list[RssiRecord] = Field(default_factory=list, alias="rssiRecords", serialization_alias="rssiRecords")

    model_config = {"populate_by_name": True}


class LatestRecord(BaseModel):
    time: datetime
    nearest_ap_mac: str | None = Field(default=None, alias="nearestApMac", serialization_alias="nearestApMac")
    nearest_ap_rssi: str | None = Field(default=None, alias="nearestApRssi", serialization_alias="nearestApRssi")

    model_config = {"populate_by_name": True}


class ScanningObservation(BaseModel):
    client_mac: str = Field(alias="clientMac", serialization_alias="clientMac")
    manufacturer: str | None = None
    ssid: str | None = None
    locations: list[ScanningLocation] = Field(default_factory=list)
    latest_record: LatestRecord = Field(alias="latestRecord", serialization_alias="latestRecord")

    model_config = {"populate_by_name": True}


class ScanningData(BaseModel):
    network_id: str = Field(alias="networkId", serialization_alias="networkId")
    observations: list[ScanningObservation]

    model_config = {"populate_by_name": True}


class ScanningPayload(BaseModel):
    version: str
    secret: str
    type: Literal["WiFi"]
    data: ScanningData


class ScanningReceiveResponse(BaseModel):
    received: int
    updated: int
    skipped: int
    client_ids: list[str]
