"""Predefined entry-quality filters for isolated 5/5 historical walk-forward tests.

All thresholds are fixed before evaluation. This is research-only and does not
change the active signal engine or paper simulator.
"""
from __future__ import annotations

from math import isfinite
from statistics import median

from backtest_engine import run_long_backtest

FILTERS = {
    "baseline_all_5of5": {},
    "rsi_at_least_55": {"rsi_min": 55.0},
    "rsi_at_least_60": {"rsi_min": 60.0},
    "relative_volume_at_least_1_2": {"volume_ratio_min": 1.2},
    "ema_spread_at_least_0_25": {"ema_spread_percent_min": 0.25},
    "atr_percent_at_most_1": {"atr_percent_max": 1.0},
    "combined_quality_filter": {
        "rsi_min": 55.0,
        "volume_ratio_min": 1.2,
        "ema_spread_percent_min": 0.25,
        "atr_percent_max": 1.0,
    },
}

METRIC_KEYS = (
    "rsi", "volume_ratio", "ema_spread_percent", "atr_percent",
)

# Fixed stress scenarios relative to the existing 0.10% fee / 0.05% slippage.
COST_SCENARIOS = {
    "base_cost": (0.001, 0.0005),
    "double_cost": (0.002, 0.001),
    "triple_cost": (0.003, 0.0015),
}


def _passes(signal, rules):
    for key in METRIC_KEYS:
        value = float(signal[key])
        if not isfinite(value):
            raise ValueError(f"Non-finite entry metric: {key}")
    return (
        signal["rsi"] >= rules.get("rsi_min", float("-inf"))
        and signal["volume_ratio"] >= rules.get("volume_ratio_min", float("-inf"))
        and signal["ema_spread_percent"] >= rules.get("ema_spread_percent_min", float("-inf"))
        and signal["atr_percent"] <= rules.get("atr_percent_max", float("inf"))
    )


def compare_entry_filters(candles, signals, initial_balance=100.0):
    """Backtest fixed entry filters on identical candles and independent capital."""
    if initial_balance <= 0 or not isfinite(float(initial_balance)):
        raise ValueError("initial_balance must be finite and positive")
    for signal in signals:
        if any(key not in signal for key in METRIC_KEYS):
            raise ValueError("Signal is missing required entry-quality metrics")

    output = {}
    for name, rules in FILTERS.items():
        selected = [signal for signal in signals if _passes(signal, rules)]
        result = run_long_backtest(
            candles, selected, initial_balance=initial_balance
        )
        trades = result["trades"]
        cost_stress = {}
        for scenario, (fee_rate, slippage_rate) in COST_SCENARIOS.items():
            stressed = run_long_backtest(
                candles, selected, initial_balance=initial_balance,
                fee_rate=fee_rate, slippage_rate=slippage_rate,
            )
            stressed_trades = stressed["trades"]
            cost_stress[scenario] = {
                "trade_count": stressed["trade_count"],
                "wins": sum(t["net_pnl"] > 0 for t in stressed_trades),
                "losses": sum(t["net_pnl"] < 0 for t in stressed_trades),
                "net_pnl": stressed["net_pnl"],
                "return_percent": stressed["return_percent"],
                "profit_factor": stressed["profit_factor"],
                "max_drawdown_percent": stressed["max_drawdown_percent"],
                "fees_paid": stressed["fees_paid"],
                "gross_profit": sum(t["net_pnl"] for t in stressed_trades if t["net_pnl"] > 0),
                "gross_loss": -sum(t["net_pnl"] for t in stressed_trades if t["net_pnl"] < 0),
            }
        output[name] = {
            "candidate_signal_count": len(selected),
            "cost_stress": cost_stress,
            "trade_count": result["trade_count"],
            "wins": sum(t["net_pnl"] > 0 for t in trades),
            "losses": sum(t["net_pnl"] < 0 for t in trades),
            "net_pnl": result["net_pnl"],
            "return_percent": result["return_percent"],
            "win_rate_percent": result["win_rate_percent"],
            "profit_factor": result["profit_factor"],
            "max_drawdown_percent": result["max_drawdown_percent"],
            "fees_paid": result["fees_paid"],
            "gross_profit": sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0),
            "gross_loss": -sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0),
        }
    return output


def aggregate_entry_filter_folds(fold_results, initial_balance=100.0):
    """Aggregate fold outcomes without compounding or carrying positions."""
    output = {}
    for name in FILTERS:
        rows = [fold[name] for fold in fold_results]
        trades = sum(row["trade_count"] for row in rows)
        wins = sum(row["wins"] for row in rows)
        gp = sum(row["gross_profit"] for row in rows)
        gl = sum(row["gross_loss"] for row in rows)
        net = sum(row["net_pnl"] for row in rows)
        active_rows = [row for row in rows if row["trade_count"] > 0]
        active_returns = [row["return_percent"] for row in active_rows]
        profitable_folds = sum(row["net_pnl"] > 0 for row in active_rows)
        losing_folds = sum(row["net_pnl"] < 0 for row in active_rows)
        cost_stress_aggregate = {}
        for scenario in COST_SCENARIOS:
            stress_rows = [
                row["cost_stress"][scenario] for row in rows
                if "cost_stress" in row and scenario in row["cost_stress"]
            ]
            stress_trades = sum(row["trade_count"] for row in stress_rows)
            stress_wins = sum(row["wins"] for row in stress_rows)
            stress_gp = sum(row["gross_profit"] for row in stress_rows)
            stress_gl = sum(row["gross_loss"] for row in stress_rows)
            stress_net = sum(row["net_pnl"] for row in stress_rows)
            active_stress = [row for row in stress_rows if row["trade_count"] > 0]
            profitable_stress = sum(row["net_pnl"] > 0 for row in active_stress)
            cost_stress_aggregate[scenario] = {
                "folds": len(stress_rows),
                "folds_with_trades": len(active_stress),
                "profitable_folds": profitable_stress,
                "losing_folds": sum(row["net_pnl"] < 0 for row in active_stress),
                "profitable_fold_rate_percent": (
                    profitable_stress / len(active_stress) * 100
                    if active_stress else 0.0
                ),
                "trade_count": stress_trades,
                "win_rate_percent": stress_wins / stress_trades * 100 if stress_trades else 0.0,
                "profit_factor": stress_gp / stress_gl if stress_gl else (None if not stress_gp else float("inf")),
                "net_pnl_sum_of_independent_folds": stress_net,
                "equal_allocation_return_percent": (
                    stress_net / (initial_balance * len(stress_rows)) * 100
                    if stress_rows else 0.0
                ),
                "fees_paid": sum(row["fees_paid"] for row in stress_rows),
                "worst_fold_max_drawdown_percent": max(
                    (row["max_drawdown_percent"] for row in stress_rows),
                    default=0.0,
                ),
            }
        output[name] = {
            "cost_stress": cost_stress_aggregate,
            "folds": len(rows),
            "folds_with_trades": len(active_rows),
            "folds_without_trades": len(rows) - len(active_rows),
            "profitable_folds": profitable_folds,
            "losing_folds": losing_folds,
            "flat_folds_with_trades": len(active_rows) - profitable_folds - losing_folds,
            "profitable_fold_rate_percent": (
                profitable_folds / len(active_rows) * 100 if active_rows else 0.0
            ),
            "median_active_fold_return_percent": (
                median(active_returns) if active_returns else 0.0
            ),
            "worst_active_fold_return_percent": (
                min(active_returns) if active_returns else 0.0
            ),
            "best_active_fold_return_percent": (
                max(active_returns) if active_returns else 0.0
            ),
            "candidate_signal_count": sum(row["candidate_signal_count"] for row in rows),
            "trade_count": trades,
            "wins": wins,
            "losses": sum(row["losses"] for row in rows),
            "win_rate_percent": wins / trades * 100 if trades else 0.0,
            "profit_factor": gp / gl if gl else (None if not gp else float("inf")),
            "net_pnl_sum_of_independent_folds": net,
            "equal_allocation_return_percent": (
                net / (initial_balance * len(rows)) * 100 if rows else 0.0
            ),
            "fees_paid": sum(row["fees_paid"] for row in rows),
            "worst_fold_max_drawdown_percent": max(
                (row["max_drawdown_percent"] for row in rows), default=0.0
            ),
        }
    return output
