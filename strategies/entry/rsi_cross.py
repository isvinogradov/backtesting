import logging
import sys
import time

from shared.enums import Band, Side
from strategies.entry.base import BaseEntryStrategy

logging.basicConfig(
    format='%(asctime)s %(name)s[%(levelname)s]: %(message)s',
    level=logging.INFO,
    stream=sys.stdout,
)
logging.Formatter.converter = time.gmtime
log = logging.getLogger("RsiCrossStrategy")


class RsiCrossStrategy(BaseEntryStrategy):
    def __init__(self, rsi_band: Band):
        super().__init__(None, None, None)
        self.rsi_band = rsi_band

    async def detect_entry_point(self) -> Side | None:
        cs = await self.api.get_klines(
            "5",
            300,
            rsi_band=self.rsi_band,
        )
        log.info(cs.get_info())
        if self.has_time_discrepancy_5m(cs.last_closed_candle.ts):
            return None

        if len(cs) < 2:
            return None
        pending_setup = None
        for i, candle in enumerate(cs.candles):
            current_rsi = candle.rsi
            if current_rsi is None:
                continue

            # First, use setups established by EARLIER candles.
            if i > 0 and pending_setup is not None:
                if (
                        candle.prev_candle.rsi is not None
                        and candle.prev_candle.rsi_ma is not None
                        and candle.rsi_ma is not None
                ):
                    if pending_setup == "LONG" and candle.crossed_up:
                        pending_setup = None
                        if i == len(cs) - 2:  # the last candle is currently forming
                            return Side.LONG
                        # Do not rearm using the signal candle.
                        continue

                    if pending_setup == "SHORT" and candle.crossed_down:
                        pending_setup = None
                        if i == len(cs) - 2:  # so we need penultimate
                            return Side.SHORT
                        # Do not rearm using the signal candle.
                        continue

            # No entry occurred, so the current closed candle may arm
            # a setup for a later candle.
            if candle.is_oversold:
                pending_setup = "LONG"
            elif candle.is_overbought:
                pending_setup = "SHORT"

        return None
