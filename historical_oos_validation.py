"""Chronological out-of-sample validation and trade diagnostics."""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median

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
    signal_condition_counts = Counter()
    trade_groups = defaultdict(list)
    for segment_index, segment in enumerate(segments):
        five = segment["candles_5m"]
        fifteen = segment["candles_15m"]
        split_index = int(len(five) * float(train_fraction))
        if split_index >= len(five) - 1:
            raise ValueError("El segmento no deja velas suficientes para test")

        signals = generate_segment_signals(
            five, fifteen, start_index=split_index
        )
        for signal in signals:
            signal_condition_counts[int(signal["conditions_met"])] += 1

        # Backtest opens at the next candle's open. Match that timestamp back
        # to the signal so score attribution only includes actually executed trades.
        index_by_timestamp = {
            int(candle["timestamp"]): i for i, candle in enumerate(five)
        }
        score_by_entry_timestamp = {
            int(five[index_by_timestamp[int(signal["timestamp"])] + 1]["timestamp"]):
                int(signal["conditions_met"])
            for signal in signals
        }
        result = run_long_backtest(
            five, signals, initial_balance=initial_balance
        )
        for trade in result["trades"]:
            score = score_by_entry_timestamp.get(int(trade["opened_at"]))
            if score is not None:
                trade_groups[score].append(trade)

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
    winners = [t for t in all_trades if t["net_pnl"] > 0]
    losers = [t for t in all_trades if t["net_pnl"] < 0]
    breakeven_count = trade_count - len(winners) - len(losers)
    wins = len(winners)
    gross_profit = sum(t["net_pnl"] for t in winners)
    gross_loss = -sum(t["net_pnl"] for t in losers)
    initial_total = initial_balance * len(rows)
    net_total = sum(row["net_pnl"] for row in rows)

    holding_minutes = [
        max(0.0, (int(t["closed_at"]) - int(t["opened_at"])) / 60_000)
        for t in all_trades
    ]
    exit_reasons = Counter(t.get("reason", "unknown") for t in all_trades)

    trade_results_by_condition_count = {}
    for score in sorted(set(signal_condition_counts) | set(trade_groups)):
        group = trade_groups[score]
        group_wins = [t for t in group if t["net_pnl"] > 0]
        group_losses = [t for t in group if t["net_pnl"] < 0]
        gross_group_profit = sum(t["net_pnl"] for t in group_wins)
        gross_group_loss = -sum(t["net_pnl"] for t in group_losses)
        trade_results_by_condition_count[str(score)] = {
            "generated_signals": signal_condition_counts[score],
            "executed_trades": len(group),
            "wins": len(group_wins),
            "losses": len(group_losses),
            "breakeven_count": len(group) - len(group_wins) - len(group_losses),
            "win_rate_percent": len(group_wins) / len(group) * 100 if group else 0.0,
            "profit_factor": gross_group_profit / gross_group_loss if gross_group_loss else (
                None if not gross_group_profit else float("inf")
            ),
            "net_pnl": sum(t["net_pnl"] for t in group),
            "mean_net_pnl": mean(t["net_pnl"] for t in group) if group else None,
        }

    return {
        "segment_count": len(rows),
        "segments_with_trades": sum(row["trade_count"] > 0 for row in rows),
        "train_fraction": float(train_fraction),
        "trade_count": trade_count,
        "wins": wins,
        "losses": len(losers),
        "breakeven_count": breakeven_count,
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
        "exit_reason_counts": dict(sorted(exit_reasons.items())),
        "mean_winning_trade_net_pnl": mean(t["net_pnl"] for t in winners) if winners else None,
        "mean_losing_trade_net_pnl": mean(t["net_pnl"] for t in losers) if losers else None,
        "mean_trade_net_pnl": mean(t["net_pnl"] for t in all_trades) if all_trades else None,
        "mean_holding_minutes": mean(holding_minutes) if holding_minutes else None,
        "median_holding_minutes": median(holding_minutes) if holding_minutes else None,
        "signal_condition_counts": dict(sorted(signal_condition_counts.items())),
        "trade_results_by_condition_count": trade_results_by_condition_count,
        "segment_results": rows,
        "portfolio_compounded_across_gaps": False,
        "test_only_trades": True,
    }
