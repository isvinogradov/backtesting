from typing import Literal

from shared.enums import Side
from strategies.exxit.base import BaseExitStrategy


class VwapExitStrategy(BaseExitStrategy):
    def __init__(self, mode: Literal["opposite", "mid"]) -> None:
        super().__init__(None)
        self.mode = mode

    async def get_tp_sl(self, for_side: Side) -> tuple[float, float]:
        cs = await self.api.get_klines(
            "5",
            300,
        )
        if for_side.is_long:
            if self.mode == "opposite":
                target = cs.last_closed_candle.vwap_bottom
            elif self.mode == "mid":
                target = cs.last_closed_candle.vwap_mid
        else:
            if self.mode == "opposite":
                target = cs.last_closed_candle.vwap_top
            elif self.mode == "mid":
                target = cs.last_closed_candle.vwap_mid

        last_price = float(await self.api.get_last_price_for_ticker())
        if target <= last_price:
            pass
