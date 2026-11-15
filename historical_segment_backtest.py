"""Run the existing closed-candle strategy over isolated, gap-free Kraken segments."""
from __future__ import annotations

from collections import defaultdict

from backtest_engine import run_long_backtest
from signal_engine import calculate_indicators

FIVE_MS = 5 * 60 * 1000
FIFTEEN_MS = 15 * 60 * 1000


def generate_segment_signals(candles_5m, candles_15m, start_index=199, minimum_conditions=4):
    """Generate causal BUY signals with a configurable 4/5-condition floor."""
    if minimum_conditions not in (4, 5):
        raise ValueError("minimum_conditions debe ser 4 o 5")
    if len(candles_5m) < 200 or len(candles_15m) < 200:
        return []

    df5 = calculate_indicators(candles_5m)
    df15 = calculate_indicators(candles_15m)
    by_15m_timestamp = {
        int(candle["timestamp"]): index
        for index, candle in enumerate(candles_15m)
    }
    signals = []

    # Last 5m candle cannot produce a tradable signal: no next open exists.
    first_index = max(199, int(start_index))
    for i in range(first_index, len(candles_5m) - 1):
        candle5 = candles_5m[i]
        close_time = int(candle5["timestamp"]) + FIVE_MS
        selected_15m_timestamp = (
            (close_time // FIFTEEN_MS) * FIFTEEN_MS - FIFTEEN_MS
        )
        j = by_15m_timestamp.get(selected_15m_timestamp)
        if j is None or j < 199:
            continue

        current = df5.iloc[i]
        trend = df15.iloc[j]
        if current.isna().any() or trend.isna().any():
            continue

        conditions = (
            current["ema20"] > current["ema200"],
            current["rsi"] > 50,
            current["macd"] > current["macd_signal"],
            current["volume"] > current["volume_sma20"],
            current["close"] > current["ema20"],
        )
        score = sum(conditions)
        if score >= minimum_conditions and trend["ema20"] > trend["ema200"]:
            atr = float(current["atr"])
            if atr > 0:
                signals.append({
                    "timestamp": int(candle5["timestamp"]),
                    "side": "BUY",
                    "atr": atr,
                    "conditions_met": int(score),
                })
    return signals


def backtest_segments(segments, initial_balance=100.0):
    """Backtest each isolated segment with a fresh balance; never bridge gaps."""
    results = []
    all_trades = []
    for segment_index, segment in enumerate(segments):
        five = segment["candles_5m"]
        fifteen = segment["candles_15m"]
        signals = generate_segment_signals(five, fifteen)
        result = run_long_backtest(
            five, signals, initial_balance=initial_balance
        )
        results.append({
            "segment_index": segment_index,
            "first_5m_timestamp": int(five[0]["timestamp"]),
            "last_5m_timestamp": int(five[-1]["timestamp"]),
            "five_minute_rows": len(five),
            "fifteen_minute_rows": len(fifteen),
            "signal_count": len(signals),
            "trade_count": result["trade_count"],
            "wins": sum(t["net_pnl"] > 0 for t in result["trades"]),
            "net_pnl": result["net_pnl"],
            "return_percent": result["return_percent"],
            "win_rate_percent": result["win_rate_percent"],
            "profit_factor": result["profit_factor"],
            "max_drawdown_percent": result["max_drawdown_percent"],
            "fees_paid": result["fees_paid"],
        })
        all_trades.extend(result["trades"])

    total_trades = len(all_trades)
    wins = sum(t["net_pnl"] > 0 for t in all_trades)
    gross_profit = sum(t["net_pnl"] for t in all_trades if t["net_pnl"] > 0)
    gross_loss = -sum(t["net_pnl"] for t in all_trades if t["net_pnl"] < 0)
    initial_total = initial_balance * len(results)
    net_total = sum(r["net_pnl"] for r in results)
    return {
        "segment_count": len(results),
        "segments_with_trades": sum(r["trade_count"] > 0 for r in results),
        "trade_count": total_trades,
        "wins": wins,
        "losses": total_trades - wins,
        "win_rate_percent": wins / total_trades * 100 if total_trades else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (
            None if not gross_profit else float("inf")
        ),
        "net_pnl_sum_of_independent_segments": net_total,
        "initial_balance_sum_of_independent_segments": initial_total,
        "equal_allocation_return_percent": (
            net_total / initial_total * 100 if initial_total else 0.0
        ),
        "fees_paid": sum(r["fees_paid"] for r in results),
        "worst_segment_max_drawdown_percent": max(
            (r["max_drawdown_percent"] for r in results), default=0.0
        ),
        "segments": results,
        "trades": all_trades,
        "portfolio_compounded_across_gaps": False,
    }
