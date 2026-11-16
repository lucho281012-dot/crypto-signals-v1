"""Disjoint chronological walk-forward validation for the isolated 5/5 strategy."""
from __future__ import annotations

from collections import Counter

from backtest_engine import run_long_backtest
from historical_segment_backtest import generate_segment_signals
from historical_trade_excursions import diagnose_trade_excursions
from historical_exit_policy_comparison import (
    compare_exit_policies, aggregate_exit_policy_folds,
)
from historical_entry_filter_comparison import (
    compare_entry_filters, aggregate_entry_filter_folds,
)

# Four consecutive, non-overlapping 12.5% test windows after a 50% warm-up.
FOLD_START_FRACTIONS = (0.50, 0.625, 0.75, 0.875)
FOLD_END_FRACTIONS = (0.625, 0.75, 0.875, 1.0)
MIN_SEGMENT_CANDLES = 400


def backtest_5of5_walk_forward(segments, initial_balance=100.0):
    """Evaluate 5/5 signals in four disjoint chronological windows per segment.

    Indicators use only candles available up to each signal. The first half of
    each contiguous segment is reserved as warm-up/history. Each subsequent
    test fold receives a fresh balance and is simulated in isolation. Segments
    shorter than 400 5m candles are excluded so every test window has at least
    50 candles; no gaps are bridged and no positions/capital carry between folds.
    """
    if initial_balance <= 0:
        raise ValueError("initial_balance debe ser positivo")

    folds = []
    exit_policy_folds = []
    entry_filter_folds = []
    excluded_short_segments = []
    for segment_index, segment in enumerate(segments):
        five = segment["candles_5m"]
        fifteen = segment["candles_15m"]
        n = len(five)
        if n < MIN_SEGMENT_CANDLES:
            excluded_short_segments.append({
                "segment_index": segment_index,
                "five_minute_rows": n,
                "reason": "fewer_than_400_candles",
            })
            continue

        # Indicators are causal; generate the 5/5 signal stream once per
        # contiguous segment, then isolate each fold's signal/entry timestamps.
        first_test_start = int(n * FOLD_START_FRACTIONS[0])
        signals = generate_segment_signals(
            five, fifteen, start_index=first_test_start, minimum_conditions=5
        )
        index_by_timestamp = {
            int(candle["timestamp"]): i for i, candle in enumerate(five)
        }
        for fold_index, (start_fraction, end_fraction) in enumerate(
            zip(FOLD_START_FRACTIONS, FOLD_END_FRACTIONS), start=1
        ):
            start = int(n * start_fraction)
            end = int(n * end_fraction)
            if end - start < 50:
                continue
            fold_signals = [
                signal for signal in signals
                if start <= index_by_timestamp[int(signal["timestamp"])] < end - 1
            ]
            test_candles = five[start:end]
            result = run_long_backtest(
                test_candles, fold_signals, initial_balance=initial_balance
            )
            trades = result["trades"]
            exit_policy_comparison = compare_exit_policies(
                test_candles, fold_signals, initial_balance=initial_balance
            )
            exit_policy_folds.append(exit_policy_comparison)
            entry_filter_comparison = compare_entry_filters(
                test_candles, fold_signals, initial_balance=initial_balance
            )
            entry_filter_folds.append(entry_filter_comparison)
            folds.append({
                "segment_index": segment_index,
                "fold_index": fold_index,
                "warmup_fraction": start_fraction,
                "test_start_fraction": start_fraction,
                "test_end_fraction": end_fraction,
                "train_5m_rows": start,
                "test_5m_rows": len(test_candles),
                "test_first_timestamp": int(test_candles[0]["timestamp"]),
                "test_last_timestamp": int(test_candles[-1]["timestamp"]),
                "test_signal_count": len(fold_signals),
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
                "exit_reason_counts": dict(sorted(
                    Counter(t.get("reason", "unknown") for t in trades).items()
                )),
                "excursion_diagnostics": diagnose_trade_excursions(test_candles, trades),
                "exit_policy_comparison": exit_policy_comparison,
                "entry_filter_comparison": entry_filter_comparison,
            })

    all_trade_count = sum(f["trade_count"] for f in folds)
    wins = sum(f["wins"] for f in folds)
    losses = sum(f["losses"] for f in folds)
    net_total = sum(f["net_pnl"] for f in folds)
    gross_profit = sum(f["gross_profit"] for f in folds)
    gross_loss = sum(f["gross_loss"] for f in folds)
    return {
        "strategy_filter": "5_of_5_only",
        "fold_count": len(folds),
        "segments_evaluated": len({f["segment_index"] for f in folds}),
        "segments_excluded_short": len(excluded_short_segments),
        "excluded_segments": excluded_short_segments,
        "folds_with_trades": sum(f["trade_count"] > 0 for f in folds),
        "trade_count": all_trade_count,
        "wins": wins,
        "losses": losses,
        "win_rate_percent": wins / all_trade_count * 100 if all_trade_count else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (None if not gross_profit else float("inf")),
        "net_pnl_sum_of_independent_folds": net_total,
        "initial_balance_sum_of_independent_folds": initial_balance * len(folds),
        "equal_allocation_return_percent": (
            net_total / (initial_balance * len(folds)) * 100 if folds else 0.0
        ),
        "fees_paid": sum(f["fees_paid"] for f in folds),
        "worst_fold_max_drawdown_percent": max(
            (f["max_drawdown_percent"] for f in folds), default=0.0
        ),
        "folds": folds,
        "folds_are_non_overlapping": True,
        "capital_and_positions_carried_between_folds": False,
        "test_only_trades": True,
        "exit_policy_comparison": aggregate_exit_policy_folds(
            exit_policy_folds, initial_balance=initial_balance
        ),
        "entry_filter_comparison": aggregate_entry_filter_folds(
            entry_filter_folds, initial_balance=initial_balance
        ),
    }
