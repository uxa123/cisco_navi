"""Meraki Scanning API形式の位置情報を共通形式へ変換する。"""

from app.schemas.models import NormalizedPosition, ScanningObservation


def normalize_observation(observation: ScanningObservation) -> NormalizedPosition | None:
    """観測データの最新位置をNormalizedPositionへ変換する。

    locationsが空の場合は位置取得失敗として扱い、既存の最新位置を上書きしない。
    """
    if not observation.locations:
        return None
    location = max(observation.locations, key=lambda item: item.time)
    return NormalizedPosition(
        client_id=observation.client_mac,
        floor_id=location.floor_plan_id,
        x=float(location.x),
        y=float(location.y),
        variance=location.variance,
        observed_at=location.time,
        # HTTP受信後の経路探索は、実機かモックかを意識しない。
        source="meraki",
    )
