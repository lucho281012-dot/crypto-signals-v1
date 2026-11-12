
import json
from statistics import mean

from historical_data import download_historical_candles
from data_feed import ema, rsi, atr
from signal_rules import evaluate_signal

# =========================================================
# MT5 SIGNALS - EXIT HORIZON AUDIT
# BTCUSDT / H1
# SIMULATION ONLY - NO REAL ORDERS
#
# Compara horizontes de 6, 12, 18 y 24 velas.
# No modifica backtest.py ni signal_rules.py.
# =========================================================

STOP_ATR = 1.5
REWARD_RISK = 2.0

FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0002

HORIZONS = [6, 12, 18, 24]
WARMUP = 100
BLOCKS = 4


def simulate_horizon(candles, start, end, max_bars):
    """Reproduce la lógica del backtest con horizonte configurable."""

    if not isinstance(candles, list):
        raise ValueError("Candles must be a list")

    if start < 0 or end >= len(candles) or start > end:
        raise ValueError("Invalid simulation indexes")

    if max_bars < 1:
        raise ValueError("Invalid holding period")

    trades = []
    i = max(start, WARMUP)

    while i < end:

        history = candles[:i + 1]

        closes = [
            float(candle[4])
            for candle in history
        ]

        indicators = {
            "close": closes[-1],
            "ema_50": ema(closes, 50),
            "rsi_14": rsi(closes, 14),
            "atr_14": atr(history, 14)
        }

        signal = evaluate_signal(indicators)["signal"]

        if signal == "WAIT":
            i += 1
            continue

        direction = 1 if signal == "BUY" else -1
        entry_index = i + 1

        if entry_index > end:
            break

        raw_entry = float(candles[entry_index][1])

        if direction == 1:
            entry = raw_entry * (1 + SLIPPAGE_RATE)
        else:
            entry = raw_entry * (1 - SLIPPAGE_RATE)

        distance = STOP_ATR * indicators["atr_14"]

        if distance <= 0:
            i += 1
            continue

        if direction == 1:
            stop = entry - distance
            target = entry + distance * REWARD_RISK
        else:
            stop = entry + distance
            target = entry - distance * REWARD_RISK

        last_index = min(
            entry_index + max_bars - 1,
            end
        )

        exit_price = None
        exit_reason = "TIME_LIMIT"
        exit_index = last_index

        for j in range(entry_index, last_index + 1):

            candle_open = float(candles[j][1])
            high = float(candles[j][2])
            low = float(candles[j][3])

            if direction == 1:

                if candle_open <= stop:
                    exit_price = candle_open
                    exit_reason = "STOP_LOSS"
                    exit_index = j
                    break

                if candle_open >= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_index = j
                    break

                stop_hit = low <= stop
                target_hit = high >= target

            else:

                if candle_open >= stop:
                    exit_price = candle_open
                    exit_reason = "STOP_LOSS"
                    exit_index = j
                    break

                if candle_open <= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_index = j
                    break

                stop_hit = high >= stop
                target_hit = low <= target

            # Same-candle SL/TP: SL has priority.
            if stop_hit:
                exit_price = stop
                exit_reason = "STOP_LOSS"
                exit_index = j
                break

            if target_hit:
                exit_price = target
                exit_reason = "TAKE_PROFIT"
                exit_index = j
                break

        if exit_price is None:
            exit_price = float(candles[last_index][4])

        if direction == 1:
            exit_fill = exit_price * (1 - SLIPPAGE_RATE)
        else:
            exit_fill = exit_price * (1 + SLIPPAGE_RATE)

        gross_pct = (
            direction * (exit_fill - entry) / entry
        ) * 100

        fees_pct = (
            FEE_RATE * (entry + exit_fill) / entry
        ) * 100

        net_pct = gross_pct - fees_pct

        trades.append({
            "signal": signal,
            "entry_index": entry_index,
            "exit_index": exit_index,
            "entry": entry,
            "exit": exit_fill,
            "reason": exit_reason,
            "net_return_pct": round(net_pct, 6),
        })

        # No overlapping positions.
        i = exit_index + 1

    return trades


def summarize(trades):
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0,
            "average_net_return_pct": None,
            "total_net_return_pct": 0,
            "compounded_return_pct": 0,
            "profit_factor": None,
            "max_drawdown_pct": 0,
        }

    returns = [
        float(t["net_return_pct"])
        for t in trades
    ]

    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]

    equity = 1.0
    peak = 1.0
    max_dd = 0.0

    for result in returns:
        equity *= 1 + result / 100
        peak = max(peak, equity)

        drawdown = (peak - equity) / peak
        max_dd = max(max_dd, drawdown)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(
            len(wins) / len(trades) * 100, 2
        ),
        "average_net_return_pct": round(
            mean(returns), 4
        ),
        "total_net_return_pct": round(
            sum(returns), 4
        ),
        "compounded_return_pct": round(
            (equity - 1) * 100, 2
        ),
        "profit_factor": round(
            gross_profit / gross_loss, 3
        ) if gross_loss else None,
        "max_drawdown_pct": round(
            max_dd * 100, 2
        ),
    }


def block_ranges(total):
    usable = total - WARMUP
    block_size = usable // BLOCKS
    ranges = []

    for number in range(BLOCKS):
        start = WARMUP + number * block_size

        if number == BLOCKS - 1:
            end = total - 1
        else:
            end = start + block_size - 1

        ranges.append((start, end))

    return ranges


def summarize_by_block(trades, ranges):
    results = []

    for number, (start, end) in enumerate(ranges, 1):
        selected = [
            t for t in trades
            if start <= t["entry_index"] <= end
        ]

        results.append({
            "block": number,
            "start_index": start,
            "end_index": end,
            **summarize(selected),
        })

    return results


def same_trade_cohort(candles, baseline_trades):
    """
    Compara cierres hipotéticos sobre las mismas operaciones
    que llegaron a 24 velas sin tocar SL ni TP.
    """

    cohort = []

    for trade in baseline_trades:

        duration = (
            trade["exit_index"]
            - trade["entry_index"] + 1
        )

        if trade["reason"] != "TIME_LIMIT":
            continue

        if duration != 24:
            continue

        cohort.append(trade)

    results = {}

    for horizon in HORIZONS:
        hypothetical = []

        for trade in cohort:

            exit_index = (
                trade["entry_index"] + horizon - 1
            )

            if exit_index >= len(candles):
                continue

            direction = (
                1 if trade["signal"] == "BUY" else -1
            )

            entry = float(trade["entry"])
            raw_exit = float(candles[exit_index][4])

            if direction == 1:
                exit_fill = raw_exit * (
                    1 - SLIPPAGE_RATE
                )
            else:
                exit_fill = raw_exit * (
                    1 + SLIPPAGE_RATE
                )

            gross_pct = (
                direction * (exit_fill - entry) / entry
            ) * 100

            fees_pct = (
                FEE_RATE * (entry + exit_fill) / entry
            ) * 100

            hypothetical.append({
                "signal": trade["signal"],
                "net_return_pct": round(
                    gross_pct - fees_pct, 6
                ),
            })

        results[str(horizon)] = {
            "same_original_trades": len(hypothetical),
            **summarize(hypothetical),
        }

    return {
        "baseline_24bar_time_limit_cohort": len(cohort),
        "hypothetical_close_results": results,
        "warning": (
            "Counterfactual close at candle close. "
            "These are not independently executable fills."
        ),
    }


def run_audit():
    candles = download_historical_candles(days=365)

    if len(candles) < 1000:
        raise ValueError("Insufficient historical candles")

    ranges = block_ranges(len(candles))

    strategy_results = {}
    simulated_trades = {}

    for horizon in HORIZONS:

        trades = simulate_horizon(
            candles,
            WARMUP,
            len(candles) - 1,
            horizon,
        )

        simulated_trades[horizon] = trades

        strategy_results[str(horizon)] = {
            "overall": summarize(trades),
            "blocks": summarize_by_block(
                trades, ranges
            ),
        }

    baseline_trades = simulated_trades[24]

    cohort_results = same_trade_cohort(
        candles,
        baseline_trades,
    )

    return {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candles": len(candles),
        "horizons_tested": HORIZONS,
        "strategy_comparison": strategy_results,
        "same_trade_cohort_comparison": cohort_results,
        "assumptions": {
            "stop_atr": STOP_ATR,
            "reward_risk": REWARD_RISK,
            "fee_per_side_pct": FEE_RATE * 100,
            "slippage_per_side_pct": SLIPPAGE_RATE * 100,
            "same_candle_priority": "STOP_LOSS",
            "no_overlapping_positions": True,
            "execution": "SIMULATION_ONLY",
        },
        "note": (
            "Diagnostic only. No strategy rules or "
            "execution settings are changed."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run_audit(), indent=2))
