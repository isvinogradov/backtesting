from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from main import RsiCross, LOCAL_TZ, RSI_THRESH_LOWER, RSI_THRESH_UPPER


@dataclass(slots=True)
class CandleBinance:
    ts: datetime
    open_: float
    high: float
    low: float
    close: float
    volume: float

    rsi: float | None = None
    rsi_ma: float | None = None
    rvol: float | None = None
    vwap_top: float | None = None
    vwap_mid: float | None = None
    vwap_bottom: float | None = None
    rsi_cross: RsiCross | None = None

    @classmethod
    def from_raw(cls, raw: Iterable[object]) -> CandleBinance:
        unix_time_raw, open_, high, low, close, volume = raw
        unix_time = int(float(unix_time_raw))

        # Support both seconds and milliseconds without silently producing a
        # date thousands of years in the future.
        if unix_time > 10_000_000_000:
            unix_time //= 1000

        return cls(
            ts=datetime.fromtimestamp(unix_time, tz=timezone.utc),
            open_=float(open_),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=float(volume),
        )

    def __str__(self) -> str:
        return (
            "CandleBinance("
            f"{self.ts.astimezone(LOCAL_TZ)}, "
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

    @property
    def price_relative_to_vwap(self) -> int:
        price = self.close
        if price == self.vwap_mid:
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
    def is_extreme(self) -> bool:
        if self.rsi is None:
            return False
        return self.rsi <= RSI_THRESH_LOWER or self.rsi >= RSI_THRESH_UPPER

    @property
    def clv(self) -> float:
        candle_range = self.high - self.low
        if candle_range == 0:
            return 0.5
        return (self.close - self.low) / candle_range

    @property
    def impulse_pct(self) -> float:
        return 100.0 * abs(self.close - self.open_) / self.open_
