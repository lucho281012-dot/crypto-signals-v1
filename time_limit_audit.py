
import json
from statistics import mean, median

from historical_data import download_historical_candles
from backtest import simulate

SYMBOL = "BTCUSDT"
TIMEFRAME = "H1"
WARMUP = 100
BLOCKS = 4
MAX_HOLDING_BARS = 24


def get_reason(trade):
    return trade.get("exit_reason", trade.get("reason", "UNKNOWN"))


def get_duration(trade):
    entry = trade.get("entry_index")
    exit_ = trade.get("exit_index")

    if entry is None or exit_ is None:
        return None

    return max(0, int(exit_) - int(entry) + 1)


def safe_average(values):
    return round(mean(values), 4) if values else None


def summarize_time_limit(trades):
    durations = []
    returns = []
    wins = 0
    losses = 0
    missing_duration = 0

    duration_buckets = {
        "1_6_bars": 0,
        "7_12_bars": 0,
        "13_18_bars": 0,
        "19_23_bars": 0,
        "24_or_more_bars": 0,
    }

    for trade in trades:
        duration = get_duration(trade)
        result = float(trade.get("net_return_pct", 0.0))

        returns.append(result)

        if result > 0:
            wins += 1
        elif result < 0:
            losses += 1

        if duration is None:
            missing_duration += 1
            continue

        durations.append(duration)

        if duration <= 6:
            duration_buckets["1_6_bars"] += 1
        elif duration <= 12:
            duration_buckets["7_12_bars"] += 1
        elif duration <= 18:
            duration_buckets["13_18_bars"] += 1
        elif duration <= 23:
            duration_buckets["19_23_bars"] += 1
        else:
            duration_buckets["24_or_more_bars"] += 1

    total = len(trades)

    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / total * 100, 2) if total else 0,
        "average_net_return_pct": safe_average(returns),
        "total_net_return_pct": round(sum(returns), 4),
        "average_duration_bars": safe_average(durations),
        "median_duration_bars": median(durations) if durations else None,
        "min_duration_bars": min(durations) if durations else None,
        "max_duration_bars": max(durations) if durations else None,
        "missing_duration": missing_duration,
        "duration_buckets": duration_buckets,
    }


def summarize_direction(trades, direction):
    selected = [
        trade for trade in trades
        if trade.get("signal") == direction
    ]

    result = summarize_time_limit(selected)

    rsi_values = [
        float(t["rsi"])
        for t in selected
        if t.get("rsi") is not None
    ]

    ema_values = [
        float(t["ema_distance_pct"])
        for t in selected
        if t.get("ema_distance_pct") is not None
    ]

    atr_values = [
        float(t["atr_pct"])
        for t in selected
        if t.get("atr_pct") is not None
    ]

    result["average_rsi"] = safe_average(rsi_values)
    result["average_ema_distance_pct"] = safe_average(ema_values)
    result["average_atr_pct"] = safe_average(atr_values)

    return result


def run_audit():
    candles = download_historical_candles(days=365)
    total = len(candles)

    if total < 1000:
        return {
            "status": "insufficient_data",
            "symbol": SYMBOL,
            "timeframe": TIMEFRAME,
            "candles": total,
        }

    usable = total - WARMUP
    block_size = usable // BLOCKS

    results = []

    for block_number in range(BLOCKS):
        start = WARMUP + block_number * block_size

        if block_number == BLOCKS - 1:
            end = total - 1
        else:
            end = start + block_size - 1

        trades = simulate(candles, start, end)

        time_limit_trades = [
            trade for trade in trades
            if get_reason(trade) == "TIME_LIMIT"
        ]

        results.append({
            "block": block_number + 1,
            "start_index": start,
            "end_index": end,
            "all_time_limit": summarize_time_limit(
                time_limit_trades
            ),
            "BUY": summarize_direction(
                time_limit_trades, "BUY"
            ),
            "SELL": summarize_direction(
                time_limit_trades, "SELL"
            ),
        })

    all_trades = [
        trade
        for block in results
        for trade in []
    ]

    # Recalculate the full-period result using the same four blocks.
    full_period_trades = []

    for block_number in range(BLOCKS):
        start = WARMUP + block_number * block_size

        if block_number == BLOCKS - 1:
            end = total - 1
        else:
            end = start + block_size - 1

        full_period_trades.extend(
            simulate(candles, start, end)
        )

    all_time_limit = [
        trade for trade in full_period_trades
        if get_reason(trade) == "TIME_LIMIT"
    ]

    return {
        "status": "success",
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "candles": total,
        "max_holding_bars": MAX_HOLDING_BARS,
        "total_time_limit": summarize_time_limit(
            all_time_limit
        ),
        "total_BUY": summarize_direction(
            all_time_limit, "BUY"
        ),
        "total_SELL": summarize_direction(
            all_time_limit, "SELL"
        ),
        "blocks": results,
        "note": (
            "Diagnostic only. No strategy rules or execution "
            "settings are changed."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run_audit(), indent=2))
