"""Meraki絶対位置とPDR相対位置の融合境界。"""

from app.schemas.models import FusedPositionState, NavigationPoint, NormalizedPosition


class PositionFusionService:
    """MVP方式: Meraki受信時に絶対位置へリセットし、以後PDRを積算する。"""

    @staticmethod
    def initialize(position: NormalizedPosition) -> FusedPositionState:
        point = NavigationPoint(
            floor_id=position.floor_id, x=position.x, y=position.y,
            observed_at=position.observed_at, source=position.source,
        )
        return FusedPositionState(
            client_id=position.client_id, meraki_position=point,
            pdr_position=point.model_copy(update={"source": "pdr_origin"}), fused_position=point,
        )

    @staticmethod
    def apply_pdr(state: FusedPositionState, pdr_position: NavigationPoint) -> FusedPositionState:
        return state.model_copy(update={"pdr_position": pdr_position, "fused_position": pdr_position})

    @staticmethod
    def correct_with_meraki(
        state: FusedPositionState, position: NormalizedPosition
    ) -> FusedPositionState:
        point = NavigationPoint(
            floor_id=position.floor_id, x=position.x, y=position.y,
            observed_at=position.observed_at, source="meraki_correction",
        )
        return state.model_copy(update={
            "meraki_position": point.model_copy(update={"source": "meraki"}),
            "pdr_position": point.model_copy(update={"source": "pdr_origin"}),
            "fused_position": point,
        })
