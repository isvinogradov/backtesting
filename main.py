from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Sequence

from shared.candle import CandleBinance
from shared.enums import Side, Outcome, RsiCross, LOCAL_TZ
from shared.functions import load_candles_from_csv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CANDLE_MINUTES = 5

RSI_THRESH_UPPER = 80.0
RSI_THRESH_LOWER = 20.0

REWARD_RISK = 1.2
ALLOWED_SIDES = {
    "LONG",
    # "SHORT",
}

# Set to None for an uncapped run. On 5-minute data, 288 candles is 24 hours.
TIME_CAP_CANDLES: int | None = 2016

# Used only to convert R expectancy into an illustrative dollar amount.
RISK_USD = 100.0

# Fees are expressed in basis points: 1 bp = 0.01% = 0.0001.
# Bitunix VIP3 futures defaults as of 2026-08-14. TP assumes a maker exit;
# SL, TIME, and END assume a taker exit. Change these if your execution differs.
ENTRY_FEE_BPS = 1.4
TP_EXIT_FEE_BPS = 1.4
OTHER_EXIT_FEE_BPS = 4.0

ONE_POSITION_AT_A_TIME = True
PRINT_TRADES = True


@dataclass(frozen=True, slots=True)
class Signal:
    entry_ix: int
    setup_ix: int
    side: Side


@dataclass(frozen=True, slots=True)
class Trade:
    signal: Signal
    exit_ix: int
    entry_price: float
    tp_price: float
    sl_price: float
    exit_price: float | None
    outcome: Outcome

    @property
    def candles_held(self) -> int:
        return self.exit_ix - self.signal.entry_ix

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.sl_price)

    @property
    def r_multiple(self) -> float | None:
        if self.exit_price is None:
            return None

        if self.risk_per_unit == 0:
            raise ZeroDivisionError("Trade has zero price risk")

        if self.signal.side is Side.LONG:
            return (
                    (self.exit_price - self.entry_price)
                    / self.risk_per_unit
            )

        return (
                (self.entry_price - self.exit_price)
                / self.risk_per_unit
        )

    @property
    def net_r_multiple(self) -> float | None:
        gross_r = self.r_multiple
        if gross_r is None or self.exit_price is None:
            return None

        exit_fee_bps = (
            TP_EXIT_FEE_BPS
            if self.outcome is Outcome.TP
            else OTHER_EXIT_FEE_BPS
        )
        fees_per_unit = (
                self.entry_price * ENTRY_FEE_BPS / 10_000
                + self.exit_price * exit_fee_bps / 10_000
        )
        return gross_r - fees_per_unit / self.risk_per_unit


def detect_signals(candles: Sequence[CandleBinance]) -> list[Signal]:
    """
    Detect signals using completed candles only.

    An extreme arms or replaces a pending setup. A matching RSI/RSI-MA cross
    on a later candle triggers it. The cross is checked before the current
    candle is allowed to re-arm a setup, so a cross can validly occur while
    RSI is still inside the extreme region.
    """
    signals: list[Signal] = []
    pending_side: Side | None = None
    setup_ix: int | None = None

    for i, candle in enumerate(candles):
        if candle.rsi is None:
            continue

        signal_side: Side | None = None
        if pending_side is Side.LONG and candle.rsi_cross is RsiCross.UP:
            signal_side = Side.LONG
        elif pending_side is Side.SHORT and candle.rsi_cross is RsiCross.DOWN:
            signal_side = Side.SHORT

        if signal_side is not None:
            if signal_side.value in ALLOWED_SIDES:
                if setup_ix is None:
                    raise AssertionError("Pending setup is missing its index")
                signals.append(Signal(i, setup_ix, signal_side))

            # A consumed signal candle cannot immediately re-arm a setup.
            pending_side = None
            setup_ix = None
            continue

        if candle.rsi <= RSI_THRESH_LOWER:
            pending_side = Side.LONG
            setup_ix = i
        elif candle.rsi >= RSI_THRESH_UPPER:
            pending_side = Side.SHORT
            setup_ix = i

    return signals


def prices_for_signal(
        candle: CandleBinance,
        side: Side,
) -> tuple[float, float, float] | None:
    entry = candle.close

    if side is Side.LONG:
        target = candle.vwap_top
        if target is None or target <= entry or candle.price_relative_to_vwap >= 2:
            return None
        reward_distance = target - entry
        risk_distance = reward_distance / REWARD_RISK
        stop = entry - risk_distance
    else:
        target = candle.vwap_bottom
        if target is None or target >= entry or candle.price_relative_to_vwap <= 4:
            return None
        reward_distance = entry - target
        risk_distance = reward_distance / REWARD_RISK
        stop = entry + risk_distance

    return entry, target, stop


def assess_trade(
        candles: Sequence[CandleBinance],
        signal: Signal,
        entry_price: float,
        tp_price: float,
        sl_price: float,
) -> Trade:
    entry_ix = signal.entry_ix
    final_ix = len(candles) - 1

    for exit_ix in range(entry_ix + 1, len(candles)):
        candle = candles[exit_ix]
        candles_held = exit_ix - entry_ix

        if signal.side is Side.LONG:
            tp_hit = candle.high >= tp_price
            sl_hit = candle.low <= sl_price
        else:
            tp_hit = candle.low <= tp_price
            sl_hit = candle.high >= sl_price

        if tp_hit and sl_hit:
            return Trade(
                signal, exit_ix, entry_price, tp_price, sl_price,
                None, Outcome.AMBIGUOUS,
            )

        if tp_hit:
            return Trade(
                signal, exit_ix, entry_price, tp_price, sl_price,
                tp_price, Outcome.TP,
            )

        if sl_hit:
            return Trade(
                signal, exit_ix, entry_price, tp_price, sl_price,
                sl_price, Outcome.SL,
            )

        # Check after TP/SL so levels touched on the final permitted candle
        # still count. Candle 288 closes exactly 24 hours after entry.
        if (
                TIME_CAP_CANDLES is not None
                and candles_held >= TIME_CAP_CANDLES
        ):
            return Trade(
                signal, exit_ix, entry_price, tp_price, sl_price,
                candle.close, Outcome.TIME,
            )

    # Force-close at the final dataset price instead of silently discarding
    # the position as None.
    return Trade(
        signal,
        final_ix,
        entry_price,
        tp_price,
        sl_price,
        candles[final_ix].close,
        Outcome.END,
    )


def run_backtest(
        candles: Sequence[CandleBinance],
        signals: Sequence[Signal],
) -> tuple[list[Trade], int, int]:
    trades: list[Trade] = []
    skipped_invalid_target = 0
    skipped_while_position_open = 0
    next_available_ix = 0

    for signal in signals:
        if ONE_POSITION_AT_A_TIME and signal.entry_ix < next_available_ix:
            skipped_while_position_open += 1
            continue

        prices = prices_for_signal(candles[signal.entry_ix], signal.side)
        if prices is None:
            skipped_invalid_target += 1
            continue

        trade = assess_trade(candles, signal, *prices)
        trades.append(trade)
        next_available_ix = trade.exit_ix

    return trades, skipped_invalid_target, skipped_while_position_open


def max_drawdown_r(r_values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0

    for value in r_values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)

    return maximum


def maximum_streak(r_values: Sequence[float], *, winning: bool) -> int:
    longest = 0
    current = 0
    for value in r_values:
        matches = value > 0 if winning else value < 0
        current = current + 1 if matches else 0
        longest = max(longest, current)
    return longest


def print_trade(trade: Trade, candles: Sequence[CandleBinance]) -> None:
    entry_candle = candles[trade.signal.entry_ix]
    setup_candle = candles[trade.signal.setup_ix]
    gross_r = trade.r_multiple
    net_r = trade.net_r_multiple
    result_text = (
        "unknown"
        if gross_r is None or net_r is None
        else f"gross={gross_r:+.3f}R, net={net_r:+.3f}R"
    )

    print(trade.signal.side.value)
    print(f"Setup: {setup_candle.ts.astimezone(LOCAL_TZ)}")
    print(entry_candle)
    print(f"TP: {trade.tp_price:.2f}")
    print(f"SL: {trade.sl_price:.2f}")
    print(
        f"-> {trade.outcome.value} in {trade.candles_held} candles "
        f"at {trade.exit_price}; {result_text}",
    )
    print()


def print_summary(
        candles: Sequence[CandleBinance],
        trades: Sequence[Trade],
        *,
        signal_count: int,
        skipped_invalid_target: int,
        skipped_while_position_open: int,
) -> None:
    outcomes = Counter(trade.outcome for trade in trades)
    scored = [
        trade
        for trade in trades
        if trade.r_multiple is not None
    ]
    gross_r_values = [
        trade.r_multiple
        for trade in scored
        if trade.r_multiple is not None
    ]
    net_r_values = [
        trade.net_r_multiple
        for trade in scored
        if trade.net_r_multiple is not None
    ]

    tp_count = outcomes[Outcome.TP]
    sl_count = outcomes[Outcome.SL]
    binary_count = tp_count + sl_count
    binary_hit_rate = (
        100.0 * tp_count / binary_count
        if binary_count
        else 0.0
    )
    positive_rate = (
        100.0 * sum(value > 0 for value in net_r_values)
        / len(net_r_values)
        if net_r_values
        else 0.0
    )
    gross_total_r = sum(gross_r_values)
    net_total_r = sum(net_r_values)
    expectancy_r = mean(net_r_values) if net_r_values else 0.0
    durations = [trade.candles_held for trade in trades]

    print("=" * 72)
    print("BACKTEST SUMMARY")
    print(f"Signals detected:             {signal_count}")
    print(f"Trades taken:                {len(trades)}")
    print(f"Skipped: position open:      {skipped_while_position_open}")
    print(f"Skipped: invalid VWAP target: {skipped_invalid_target}")
    print(
        f"TP / SL / TIME / END / AMB:  {tp_count} / {sl_count} / "
        f"{outcomes[Outcome.TIME]} / {outcomes[Outcome.END]} / "
        f"{outcomes[Outcome.AMBIGUOUS]}",
    )
    print(f"TP hit rate (TP/SL only):    {binary_hit_rate:.2f}%")
    print(f"Net positive close rate:     {positive_rate:.2f}%")
    print(f"Gross result:                {gross_total_r:+.3f}R")
    print(f"Modeled trading costs:       {gross_total_r - net_total_r:.3f}R")
    print(f"Net result:                  {net_total_r:+.3f}R")
    print(f"Net expectancy:              {expectancy_r:+.3f}R/trade")
    dollar_expectancy = expectancy_r * RISK_USD
    dollar_sign = "+" if dollar_expectancy >= 0 else "-"
    print(
        f"At ${RISK_USD:.0f} risk:              "
        f"{dollar_sign}${abs(dollar_expectancy):.2f}/trade",
    )
    print(f"Maximum net drawdown:        {max_drawdown_r(net_r_values):.3f}R")
    print(
        "Maximum winning streak:      "
        f"{maximum_streak(net_r_values, winning=True)}",
    )
    print(
        "Maximum losing streak:       "
        f"{maximum_streak(net_r_values, winning=False)}",
    )

    if durations:
        print(f"Median duration:             {median(durations):.1f} candles")
        print(f"Mean duration:               {mean(durations):.1f} candles")
        print(
            "Total position exposure:     "
            f"{sum(durations) * CANDLE_MINUTES / 60:.1f} hours",
        )

    monthly: dict[str, list[float]] = defaultdict(list)
    for trade in scored:
        r_value = trade.net_r_multiple
        if r_value is None:
            continue
        entry_ts = candles[trade.signal.entry_ix].ts
        month_key = entry_ts.astimezone(LOCAL_TZ).strftime("%Y-%m")
        monthly[month_key].append(r_value)

    print("\nNET MONTHLY RESULTS")
    for month_key in sorted(monthly):
        values = monthly[month_key]
        print(
            f"{month_key}: {sum(values):+7.3f}R across {len(values):3d} trades "
            f"({mean(values):+.3f}R/trade)",
        )


def main(csv_path: Path) -> None:
    if REWARD_RISK <= 0:
        raise ValueError("REWARD_RISK must be greater than zero")
    if TIME_CAP_CANDLES is not None and TIME_CAP_CANDLES <= 0:
        raise ValueError("TIME_CAP_CANDLES must be positive or None")
    if min(ENTRY_FEE_BPS, TP_EXIT_FEE_BPS, OTHER_EXIT_FEE_BPS) < 0:
        raise ValueError("Fee rates cannot be negative")

    candles = load_candles_from_csv(csv_path)
    signals = detect_signals(candles)
    trades, invalid_target_count, open_position_count = run_backtest(
        candles,
        signals,
    )

    if PRINT_TRADES:
        for trade in trades:
            print_trade(trade, candles)

    print_summary(
        candles,
        trades,
        signal_count=len(signals),
        skipped_invalid_target=invalid_target_count,
        skipped_while_position_open=open_position_count,
    )


if __name__ == "__main__":
    csv_loc = Path("btc_data_2026_5m.csv")
    main(csv_loc)
