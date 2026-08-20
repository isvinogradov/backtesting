from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from shared.enums import RsiCross, Symbol, Band
from shared.functions import calc_vwap_bands, rsi_rvol_sma_from_candles


def unix_str_to_datetime(raw: str) -> datetime:
    """
    Support both seconds and milliseconds without silently producing a
    date thousands of years in the future.
    """
    unix_time = int(float(raw))
    if unix_time > 10_000_000_000:
        unix_time //= 1000
    return datetime.fromtimestamp(unix_time, tz=timezone.utc)


class CandleSet:
    def __init__(
            self,
            source: str,
            symbol: Symbol,
            tf: str,
            candles: list[Candle],
            rsi_band: Band = Band(0.0, 100.0),
            rvol_band: Band | None = None,
    ):
        self.source = source
        self.symbol = symbol
        self.tf = tf
        self.candles = candles
        self.rsi_band = rsi_band
        self.rvol_band = rvol_band

    @classmethod
    def from_raw(
            cls,
            raw_data: Iterable,
            source: str,
            symbol: Symbol,
            tf: str,
            rsi_band: Band | None = None,
    ) -> CandleSet:
        cs = CandleSet(
            source=source,
            symbol=symbol,
            tf=tf,
            candles=[],
            rvol_band=None,
        )
        if rsi_band is not None:
            cs.rsi_band = rsi_band
        cs.candles = [Candle.from_raw(raw=z, parent_set=cs) for z in raw_data]
        cs.calc_indicators()
        return cs

    def __len__(self) -> int:
        return len(self.candles)

    @property
    def current_candle(self) -> Candle:
        return self.candles[-1]

    @property
    def last_closed_candle(self) -> Candle:
        return self.candles[-2]

    def get_info(self) -> str:
        return (f"Last candle: {self.last_closed_candle.close}, "
                f"RSI {round(self.last_closed_candle.rsi, 2)}, "
                f"MA {round(self.last_closed_candle.rsi_ma, 2)}; "
                f"Current: {self.current_candle.close}, "
                f"{round(self.current_candle.rsi, 2)}, "
                f"{round(self.current_candle.rsi_ma, 2)}")

    def calc_indicators(self) -> None:
        rsi, rvol, rsi_sma = rsi_rvol_sma_from_candles(self.candles)
        vwap_mid, vwap_top, vwap_bottom = calc_vwap_bands(
            self.candles,
            1,
            session_key=lambda cnd: (
                cnd.ts.astimezone(timezone.utc).date()
            ),
        )
        for i, candle in enumerate(self.candles):
            candle.ix = i
            candle.rsi = rsi[i]
            candle.rvol = rvol[i]
            candle.rsi_ma = rsi_sma[i]
            candle.vwap_top = vwap_top[i]
            candle.vwap_mid = vwap_mid[i]
            candle.vwap_bottom = vwap_bottom[i]

            # detect RSI MA cross
            prev = self.candles[i - 1]
            if (
                    prev.rsi is None or prev.rsi_ma is None
                    or candle.rsi is None or candle.rsi_ma is None
            ):
                continue
            if prev.rsi <= prev.rsi_ma and candle.rsi > candle.rsi_ma:
                candle.rsi_cross = RsiCross.UP
            elif prev.rsi >= prev.rsi_ma and candle.rsi < candle.rsi_ma:
                candle.rsi_cross = RsiCross.DOWN


@dataclass(slots=True)
class Candle:
    # BASICS
    ts: datetime
    open_: float
    high: float
    low: float
    close: float
    volume: float

    # GENERAL INFO
    parent_set: CandleSet
    ix: int | None = None

    # INDICATORS (populated after init)
    rsi: float | None = None
    rsi_ma: float | None = None
    rvol: float | None = None
    vwap_top: float | None = None
    vwap_mid: float | None = None
    vwap_bottom: float | None = None
    rsi_cross: RsiCross | None = None

    @property
    def next_candle(self) -> Candle:
        return self.parent_set.candles[self.ix + 1]

    @property
    def prev_candle(self) -> Candle:
        return self.parent_set.candles[self.ix - 1]

    @classmethod
    def from_raw(
            cls,
            raw: Iterable[str],
            parent_set: CandleSet,
    ) -> Candle:
        unix_time_raw, open_, high, low, close, volume, *_ = raw
        return cls(
            ts=unix_str_to_datetime(unix_time_raw),
            open_=float(open_),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=float(volume),
            parent_set=parent_set,
        )

    def __str__(self) -> str:
        return (
            "CandleBinance("
            f"{self.ts.astimezone(ZoneInfo("Asia/Nicosia"))}, "
            f"open={self.open_}, "
            f"high={self.high}, "
            f"low={self.low}, "
            f"close={self.close}, "
            f"RSI={self.rsi}, "
            f"RSI MA={self.rsi_ma}, "
            f"VWAP Top={self.vwap_top}, "
            f"VWAP Middle={self.vwap_mid}, "
            f"VWAP Bottom={self.vwap_bottom}, "
            f"RSI cross={self.rsi_cross}"
            ")"
        )

    def __repr__(self) -> str:
        return f"{self.ts}|o {self.open_}|h {self.high}|c {self.close}"

    @property
    def price_relative_to_vwap(self) -> int:
        if self.close == self.vwap_mid:
            return 3
        if self.close > self.vwap_top:
            return 5
        if self.close < self.vwap_bottom:
            return 1
        if self.vwap_mid > self.close >= self.vwap_bottom:
            return 2
        if self.vwap_mid < self.close <= self.vwap_top:
            return 4
        raise RuntimeError("Unknown price state")

    @property
    def is_oversold(self) -> bool:
        if self.rsi is None:
            return False
        return self.rsi <= self.parent_set.rsi_band.low

    @property
    def is_overbought(self) -> bool:
        if self.rsi is None:
            return False
        return self.rsi >= self.parent_set.rsi_band.high

    @property
    def is_extreme(self) -> bool:
        return self.is_overbought or self.is_oversold

    def is_green(self) -> bool:
        return self.close > self.open_

    @property
    def crossed_up(self) -> bool:
        return self.rsi_cross == RsiCross.UP

    @property
    def crossed_down(self) -> bool:
        return self.rsi_cross == RsiCross.DOWN

    @property
    def is_full_body(self) -> bool:
        return abs(self.close - self.open_) == abs(self.high - self.low)

    @property
    def clv_pct(self) -> float:
        """
        CLV = Close Location Value - pct of candle where close occurred.
        CLV of 1.0 means close == high, CLVof 0.0 means close == low.
        """
        try:
            return (self.close - self.low) / (self.high - self.low)
        except ZeroDivisionError:
            return 0.5

    @property
    def impulse_pct(self) -> float:
        """
        Body delta % (aka impulse) = absolute percentage change of price for
        the candle.
        """
        return 100.0 * abs(self.close - self.open_) / self.open_
