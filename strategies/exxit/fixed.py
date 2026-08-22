from shared.enums import Side
from strategies.exxit.base import BaseExitStrategy


class FixedExitStrategy(BaseExitStrategy):
    """ Exit parameters are fixed percentages """

    def __init__(
            self,
            tp_pct: float | None = None,
            sl_pct: float | None = None,
            rr: float | None = None,  # '2' means SL is 2x smaller than TP
    ) -> None:
        super().__init__(None)
        if tp_pct and sl_pct and rr:
            raise ValueError("You must provide exactly two arguments")
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.rr = rr

    async def get_tp_sl(self, for_side: Side) -> tuple[float, float]:
        last_price = float(await self.api.get_last_price_for_ticker())
        if self.tp_pct and self.sl_pct:
            if for_side.is_long:
                tp_abs = last_price * (1 + self.tp_pct / 100)  # LONG
                sl_abs = last_price * (1 - self.sl_pct / 100)
            else:
                tp_abs = last_price * (1 - self.tp_pct / 100)  # SHORT
                sl_abs = last_price * (1 + self.sl_pct / 100)
        elif self.tp_pct and self.rr:
            if for_side.is_long:
                tp_abs = last_price * (1 + self.tp_pct / 100)  # LONG
            else:
                tp_abs = last_price * (1 - self.tp_pct / 100)  # SHORT
            delta = tp_abs - last_price
            sl_abs = last_price - (delta / self.rr)
        elif self.sl_pct and self.rr:
            if for_side.is_long:
                sl_abs = last_price * (1 - self.sl_pct / 100)  # LONG
            else:
                sl_abs = last_price * (1 + self.sl_pct / 100)  # SHORT
            delta = last_price - sl_abs
            tp_abs = last_price + (delta * self.rr)
        else:
            raise ValueError("You must provide exactly two arguments")
        return round(tp_abs, 5), round(sl_abs, 5)
