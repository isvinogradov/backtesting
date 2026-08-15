import math
from collections.abc import Callable, Hashable
from pathlib import Path

import pandas as pd

from shared.candle import CandleBinance
from shared.enums import RsiCross, Symbol

# datetime short format
DT_SHORT = "%d.%m.%Y %H:%M:%S"
VWAP_BAND_MULTIPLIER = 1.0


def load_candles_from_csv(filename: Path) -> list[CandleBinance]:
    frame = pd.read_csv(filename)
    if frame.shape[1] < 6:
        raise ValueError("CSV must contain at least six OHLCV columns")

    candles = [
        CandleBinance.from_raw(raw, source="Binance", symbol=Symbol.BTC, tf="5m")
        for raw in frame.iloc[:, :6].itertuples(index=False, name=None)
    ]

    if not candles:
        raise ValueError("CSV contains no candles")

    if any(a.ts >= b.ts for a, b in zip(candles, candles[1:])):
        raise ValueError("Candles must be strictly sorted by timestamp")

    rsi_series, rvol_series, rsi_ma_series = (
        rsi_rvol_sma_from_candles(candles)
    )

    vwap_mid, vwap_top, vwap_bottom = calc_vwap_bands(
        candles,
        VWAP_BAND_MULTIPLIER,
        session_key=lambda candle: candle.ts.date(),
    )

    for i, candle in enumerate(candles):
        candle.rsi = rsi_series[i]
        candle.rvol = rvol_series[i]
        candle.rsi_ma = rsi_ma_series[i]
        candle.vwap_top = vwap_top[i]
        candle.vwap_mid = vwap_mid[i]
        candle.vwap_bottom = vwap_bottom[i]

        # Do not use candles[-1] as the previous candle when i == 0.
        if i == 0:
            continue

        previous = candles[i - 1]
        if (
                previous.rsi is None
                or previous.rsi_ma is None
                or candle.rsi is None
                or candle.rsi_ma is None
        ):
            continue

        if previous.rsi <= previous.rsi_ma and candle.rsi > candle.rsi_ma:
            candle.rsi_cross = RsiCross.UP
        elif previous.rsi >= previous.rsi_ma and candle.rsi < candle.rsi_ma:
            candle.rsi_cross = RsiCross.DOWN

    return candles


def calc_rsi_sma(
        closes: list[float],
        length: int = 14,
) -> list[float | None]:
    """Return SMA(length) of Wilder RSI(length), aligned with closes."""
    result: list[float | None] = [None] * len(closes)

    if length <= 0:
        raise ValueError("length must be greater than 0")

    if len(closes) <= length:
        return result

    gains: list[float] = []
    losses: list[float] = []

    for i in range(1, length + 1):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length

    rsi_values: list[float] = []

    for i in range(length, len(closes)):
        if i > length:
            change = closes[i] - closes[i - 1]
            gain = max(change, 0.0)
            loss = max(-change, 0.0)

            avg_gain = (avg_gain * (length - 1) + gain) / length
            avg_loss = (avg_loss * (length - 1) + loss) / length

        if avg_loss == 0:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - 100.0 / (1.0 + rs)

        rsi_values.append(rsi)

        if len(rsi_values) >= length:
            result[i] = sum(rsi_values[-length:]) / length

    return result


def rsi_rvol_sma_from_candles(
        candles: list,  # candle class
) -> tuple[
    list[float | None],
    list[float | None],
    list[float | None],
]:
    """ Calculate RSI and RVOL series based on candles """
    closes: list[float] = []
    volumes: list[float] = []
    for c in candles:
        closes.append(c.close)
        volumes.append(c.volume)
    return (
        calc_rsi(closes, 14),
        fast_rvol(volumes, 20),
        calc_rsi_sma(closes, 14),
    )


def calc_rsi(
        closes: list[float],
        length: int,
) -> list[float | None]:
    """
    Return Wilder’s RSI (smoothed gains/losses) per bar;
    None until enough data.
    """
    n = len(closes)
    if length <= 0 or n < length + 1:
        return [None] * n

    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    out: list[float | None] = [None] * n

    avg_gain = sum(gains[:length]) / length
    avg_loss = sum(losses[:length]) / length

    def calc_rsi(g: float, l: float) -> float:
        """Compute RSI value from average gain/loss."""
        if l == 0:
            return 100.0
        rs = g / l
        return 100.0 - (100.0 / (1.0 + rs))

    first_idx = length
    out[first_idx] = calc_rsi(avg_gain, avg_loss)

    for i in range(length + 1, n):
        gain = gains[i - 1]
        loss = losses[i - 1]
        avg_gain = (avg_gain * (length - 1) + gain) / length
        avg_loss = (avg_loss * (length - 1) + loss) / length
        out[i] = calc_rsi(avg_gain, avg_loss)

    return out


def calc_vwap_bands(
        candles: list[Candle],
        band_mult: float = 2.0,
        session_key: Callable[[Candle], Hashable] | None = None,
) -> tuple[
    list[float | None],
    list[float | None],
    list[float | None],
]:
    """
    Calculate VWAP and volume-weighted standard-deviation bands.

    Returns:
        middle: VWAP
        upper:  VWAP + band_mult * standard deviation
        lower:  VWAP - band_mult * standard deviation

    Price source:
        (high + low + close) / 3

    If session_key is None, VWAP is cumulative from the first candle.

    session_key can be used to reset VWAP, for example once per UTC day.
    """
    if band_mult < 0:
        raise ValueError("band_mult must not be negative")

    middle: list[float | None] = []
    upper: list[float | None] = []
    lower: list[float | None] = []

    current_session: Hashable | None = None
    first_candle = True

    total_volume = 0.0
    weighted_mean = 0.0
    weighted_m2 = 0.0

    for candle in candles:
        session = (
            session_key(candle)
            if session_key is not None
            else None
        )

        if (
                first_candle
                or (
                session_key is not None
                and session != current_session
        )
        ):
            current_session = session
            total_volume = 0.0
            weighted_mean = 0.0
            weighted_m2 = 0.0
            first_candle = False

        volume = float(candle.volume)

        if volume < 0:
            raise ValueError(
                f"Candle at {candle.ts} has negative volume",
            )

        typical_price = (candle.high + candle.low + candle.close) / 3.0

        if volume > 0:
            new_total_volume = total_volume + volume

            # Weighted Welford algorithm
            delta = typical_price - weighted_mean

            weighted_mean += (
                    volume
                    / new_total_volume
                    * delta
            )

            weighted_m2 += (
                    volume
                    * delta
                    * (typical_price - weighted_mean)
            )

            total_volume = new_total_volume

        if total_volume == 0:
            middle.append(None)
            upper.append(None)
            lower.append(None)
            continue

        variance = max(
            weighted_m2 / total_volume,
            0.0,
        )
        std_dev = math.sqrt(variance)

        vwap = weighted_mean

        middle.append(vwap)
        upper.append(vwap + band_mult * std_dev)
        lower.append(vwap - band_mult * std_dev)

    return middle, upper, lower


def fast_rvol(
        volumes: list[float],
        window: int = 20,
) -> list[float | None]:
    """
    Return Relative Volume (RVOL) per bar: volume[i] / SMA(volume, window).
    Yields None until enough data (i < window-1) or when the SMA is zero.

    Args:
        volumes: List of volumes, oldest -> newest.
        window:  Lookback length for the average (default 20).

    Returns:
        List of RVOL values aligned to input; each item is a float or None.
    """
    n = len(volumes)
    if window <= 0 or n == 0:
        return [None] * n

    out: list[float | None] = [None] * n
    if n < window:
        return out

    rolling_sum = sum(volumes[:window])
    # first RVOL at index window-1
    sma = rolling_sum / window
    out[window - 1] = (volumes[window - 1] / sma) if sma != 0 else None

    for i in range(window, n):
        rolling_sum += volumes[i] - volumes[i - window]
        sma = rolling_sum / window
        out[i] = (volumes[i] / sma) if sma != 0 else None

    return out
