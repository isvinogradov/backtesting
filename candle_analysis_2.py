from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from shared.candle import Candle, CandleSet
from shared.enums import Band, Side, Symbol

my_tz = ZoneInfo('Asia/Nicosia')
# WORKING_HRS_MIN = 6
# WORKING_HRS_MAX = 22
RSI_BAND = Band(20.0, 80.0)
TP2 = 0.16
SL2 = 0.16
RR = TP2 / SL2
ALLOWED_SIDES = {
    Side.LONG,
    # "SHORT",
}
TIME_CAP_CANDLES = 288  # 8 - 1


def calc_avg_profit(
        win_rate: float,
        rr_ratio: float,
        risk_abs: float,
) -> float:
    """
    Calculate expected average profit per trade.

    win_rate: percentage from 0 to 100
    rr_ratio: reward/risk ratio, e.g. 1.5
    risk_abs: money lost when SL is hit
    """
    if not 0 <= win_rate <= 100:
        raise ValueError("win_rate must be between 0 and 100")

    if rr_ratio <= 0:
        raise ValueError("rr_ratio must be greater than 0")

    if risk_abs <= 0:
        raise ValueError("risk_abs must be greater than 0")

    win_probability = win_rate / 100
    loss_probability = 1 - win_probability

    avg_profit_r = (
            win_probability * rr_ratio
            - loss_probability
    )

    return avg_profit_r * risk_abs


def load_candles_from_csv(
        filename: str | Path,
        rsi_band: Band | None = None,
) -> list[Candle]:
    """
    Convert raw data from .csv file to Python list.
    :param filename: .csv file to use
    :param rsi_band: rsi band to use
    :return: list of candle objects
    """
    df = pd.read_csv(filename)
    rows = [x for _, x in df.iterrows()]
    cs = CandleSet.from_raw(
        rows,
        "Binance",
        symbol=Symbol.BTC,
        tf="5",
        rsi_band=rsi_band,
    )
    return cs.candles


def analyze_all_candles(candles: list[Candle]) -> None:
    tps, sls = 0, 0
    i = 0
    while i < len(candles):
        can = candles[i]

        # exclude bad time window
        # if WORKING_HRS_MIN < can.ts.astimezone(my_tz).hour < WORKING_HRS_MAX:
        #     i += 1
        #     continue

        if not can.is_extreme:
            i += 1
            continue

        if i < (len(candles) - 1) and candles[i + 1].is_extreme:
            i += 1
            continue  # exclude successive extremes

        # find nearest cross with appropriate direction
        ii = 0
        while True:
            ii += 1
            index_to_check = i + ii
            candle_to_check = candles[index_to_check]
            if not candle_to_check.rsi_cross:
                continue
            if can.is_oversold and candle_to_check.crossed_down:
                continue
            if can.is_overbought and candle_to_check.crossed_up:
                continue

            # cross found
            # tp_abs = candle_to_check.close * (1 + TP2 / 100)
            # sl_abs = candle_to_check.close * (1 - SL2 / 100)
            tp_abs = candle_to_check.vwap_top
            sl_abs = candle_to_check.close - (tp_abs - candle_to_check.close)
            side = Side.LONG
            if candle_to_check.crossed_down:  # SHORT
                # tp_abs = candle_to_check.close * (1 - TP2 / 100)
                # sl_abs = candle_to_check.close * (1 + SL2 / 100)
                tp_abs = candle_to_check.vwap_bottom
                sl_abs = candle_to_check.close + (candle_to_check.close - tp_abs)
                side = Side.SHORT

            if side.is_long and tp_abs <= candle_to_check.close:
                continue
            if side.is_short and tp_abs >= candle_to_check.close:
                continue

            print(side)
            # print(can)
            print(candle_to_check)
            print("TP: ", round(tp_abs, 2))
            print("SL: ", round(sl_abs, 2))
            pos_result, candles_taken, exit_price = excursion_check(
                candles,
                entry_ix=index_to_check,
                tp_abs=tp_abs,
                sl_abs=sl_abs,
                side=side,
            )

            # calc stats
            if side in ALLOWED_SIDES:
                if pos_result == "TP":
                    tps += 1
                if pos_result == "SL":
                    sls += 1
            print(
                f"-> {pos_result} result reached in {candles_taken} candles "
                f"with {exit_price=}",
            )
            print()
            i = index_to_check
            break
        i += 1

    wr = tps / (tps + sls)
    print(tps, sls, tps + sls)
    print(
        f"WinRate={round(wr * 100)}%; {RR=}; "
        f"AvgProfit=${round(calc_avg_profit(wr * 100, RR, 100))}",
    )


def excursion_check(
        candles: list[Candle],
        entry_ix: int,
        tp_abs: float,
        sl_abs: float,
        side: Side,
) -> tuple[str, int, float]:
    """
    Returns:
        ("TP", candles_count)
        ("SL", candles_count)
        -1 if neither TP nor SL was reached

    Assessment starts from the candle after entry_ix.
    """
    if not 0 <= entry_ix < len(candles):
        raise IndexError("entry_ix is outside the candles list")

    if side.is_long:
        if tp_abs <= sl_abs:
            raise ValueError("For LONG, tp_abs must be above sl_abs")

    elif side.is_short:
        if tp_abs >= sl_abs:
            raise ValueError("For SHORT, tp_abs must be below sl_abs")

    else:
        raise ValueError("side must be 'LONG' or 'SHORT'")

    for candles_count, candle in enumerate(
            candles[entry_ix + 1:],
            start=1,
    ):
        if side.is_long:
            tp_hit = candle.high >= tp_abs
            sl_hit = candle.low <= sl_abs
        else:
            tp_hit = candle.low <= tp_abs
            sl_hit = candle.high >= sl_abs

        if tp_hit and sl_hit:
            return "AMBIGUOUS", candles_count, -1
            raise ValueError(
                f"Both TP and SL were touched after {candles_count} candles "
                f"at {candle.ts}; order cannot be determined from OHLC data",
            )

        if tp_hit:
            return "TP", candles_count, tp_abs

        if sl_hit:
            return "SL", candles_count, sl_abs

        if candles_count > TIME_CAP_CANDLES:
            return "TIME", candles_count, candle.close

    return "None", -1, -1


if __name__ == '__main__':
    cds = load_candles_from_csv(
        f"{Symbol.BTC.lower()}_data_2026_5m.csv",
        rsi_band=RSI_BAND,
    )
    analyze_all_candles(cds)
