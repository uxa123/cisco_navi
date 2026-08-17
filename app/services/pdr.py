"""スマートフォンで算出済みのPDR移動量を地図座標へ反映する。"""

import math

from app.schemas.models import MovementRequest, NavigationPoint


class PdrService:
    """0度=北(+Y)、90度=東(+X)として位置を更新する。"""

    def apply(self, origin: NavigationPoint, movement: MovementRequest) -> NavigationPoint:
        distance = movement.movement_distance()
        radians = math.radians(movement.heading_deg % 360)
        return NavigationPoint(
            floor_id=origin.floor_id,
            x=origin.x + distance * math.sin(radians),
            y=origin.y + distance * math.cos(radians),
            observed_at=movement.timestamp,
            source="pdr",
        )
