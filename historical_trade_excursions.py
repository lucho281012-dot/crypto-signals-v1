"""Post-trade MFE/MAE and holding-time diagnostics for long backtests.

Excursions are measured from the simulated entry price in initial-risk (R)
units, using OHLC bars from entry through exit. OHLC cannot reveal intrabar
ordering, so these are descriptive ranges, not executable path assumptions.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median


def diagnose_trade_excursions(candles, trades):
    """Summarize each closed trade's maximum favorable/adverse excursion."""
    index_by_timestamp = {int(c["timestamp"]): i for i, c in enumerate(candles)}
    rows = []
    for trade in trades:
        entry_index = index_by_timestamp.get(int(trade["opened_at"]))
        exit_index = index_by_timestamp.get(int(trade["closed_at"]))
        if entry_index is None or exit_index is None or exit_index < entry_index:
            raise ValueError("Trade timestamps do not map to an ordered candle range")
        entry = float(trade["entry"])
        risk_distance = entry - float(trade["stop"])
        if risk_distance <= 0:
            raise ValueError("Trade risk distance must be positive")
        window = candles[entry_index:exit_index + 1]
        highest = max(float(c["high"]) for c in window)
        lowest = min(float(c["low"]) for c in window)
        mfe_r = max(0.0, highest - entry) / risk_distance
        mae_r = max(0.0, entry - lowest) / risk_distance
        hold_minutes = (int(trade["closed_at"]) - int(trade["opened_at"])) / 60000
        rows.append({
            "reason": trade.get("reason", "unknown"),
            "net_pnl": float(trade["net_pnl"]),
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "hold_minutes": hold_minutes,
        })

    if not rows:
        return {
            "trade_count": 0, "avg_hold_minutes": 0.0,
            "median_hold_minutes": 0.0, "avg_mfe_r": 0.0,
            "median_mfe_r": 0.0, "avg_mae_r": 0.0,
            "median_mae_r": 0.0, "mfe_threshold_counts": {},
            "exit_reason_counts": {}, "by_exit_reason": {},
        }

    by_reason = defaultdict(list)
    for row in rows:
        by_reason[row["reason"]].append(row)
    thresholds = (0.5, 1.0, 1.5, 2.0)
    return {
        "trade_count": len(rows),
        "avg_hold_minutes": mean(r["hold_minutes"] for r in rows),
        "median_hold_minutes": median(r["hold_minutes"] for r in rows),
        "avg_mfe_r": mean(r["mfe_r"] for r in rows),
        "median_mfe_r": median(r["mfe_r"] for r in rows),
        "avg_mae_r": mean(r["mae_r"] for r in rows),
        "median_mae_r": median(r["mae_r"] for r in rows),
        "mfe_threshold_counts": {
            f"at_least_{threshold:g}R": sum(r["mfe_r"] >= threshold for r in rows)
            for threshold in thresholds
        },
        "exit_reason_counts": dict(sorted(Counter(r["reason"] for r in rows).items())),
        "by_exit_reason": {
            reason: {
                "trade_count": len(group),
                "avg_mfe_r": mean(r["mfe_r"] for r in group),
                "avg_mae_r": mean(r["mae_r"] for r in group),
                "avg_hold_minutes": mean(r["hold_minutes"] for r in group),
                "net_pnl": sum(r["net_pnl"] for r in group),
            }
            for reason, group in sorted(by_reason.items())
        },
    }
