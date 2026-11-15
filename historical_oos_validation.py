"""Chronological out-of-sample validation on untouched trailing data."""
from __future__ import annotations

from backtest_engine import run_long_backtest
from historical_segment_backtest import generate_segment_signals


def backtest_out_of_sample(segments, initial_balance=100.0, train_fraction=0.70):
    """Train period is indicator warm-up only; all simulated trades are in the tail.

    Indicators are calculated causally over each full segment, but signal
    generation is disabled until the chronological split. Each segment has an
    independent balance and no position is carried across gaps.
    """
    if not 0.5 <= float(train_fraction) < 0.9:
        raise ValueError("train_fraction debe estar entre 0.5 y menos de 0.9")

    rows = []
    all_trades = []
    for segment_index, segment in enumerate(segments):
        five = segment["candles_5m"]
        fifteen = segment["candles_15m"]
        split_index = int(len(five) * float(train_fraction))
        if split_index >= len(five) - 1:
            raise ValueError("El segmento no deja velas suficientes para test")

        signals = generate_segment_signals(
            five, fifteen, start_index=split_index
        )
        result = run_long_backtest(
            five, signals, initial_balance=initial_balance
        )
        rows.append({
            "segment_index": segment_index,
            "train_fraction": float(train_fraction),
            "train_5m_rows": split_index,
            "test_5m_rows": len(five) - split_index,
            "train_last_5m_timestamp": int(five[split_index - 1]["timestamp"]),
            "test_first_5m_timestamp": int(five[split_index]["timestamp"]),
            "test_last_5m_timestamp": int(five[-1]["timestamp"]),
            "test_signal_count": len(signals),
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

    trade_count = len(all_trades)
    wins = sum(t["net_pnl"] > 0 for t in all_trades)
    gross_profit = sum(t["net_pnl"] for t in all_trades if t["net_pnl"] > 0)
    gross_loss = -sum(t["net_pnl"] for t in all_trades if t["net_pnl"] < 0)
    initial_total = initial_balance * len(rows)
    net_total = sum(row["net_pnl"] for row in rows)
    return {
        "segment_count": len(rows),
        "segments_with_trades": sum(row["trade_count"] > 0 for row in rows),
        "train_fraction": float(train_fraction),
        "trade_count": trade_count,
        "wins": wins,
        "losses": trade_count - wins,
        "win_rate_percent": wins / trade_count * 100 if trade_count else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (
            None if not gross_profit else float("inf")
        ),
        "net_pnl_sum_of_independent_segments": net_total,
        "initial_balance_sum_of_independent_segments": initial_total,
        "equal_allocation_return_percent": (
            net_total / initial_total * 100 if initial_total else 0.0
        ),
        "fees_paid": sum(row["fees_paid"] for row in rows),
        "worst_segment_max_drawdown_percent": max(
            (row["max_drawdown_percent"] for row in rows), default=0.0
        ),
        "segment_results": rows,
        "portfolio_compounded_across_gaps": False,
        "test_only_trades": True,
    }
