"""Conservative OHLC counterfactual comparison of alternative exit policies.

Research-only: baseline is delegated to backtest_engine. Alternative policies
use stop-first handling when stop and favorable thresholds are both touched in
one OHLC candle. Stops changed by a candle's high become active only on the
next candle; no intrabar ordering is inferred.
"""
from __future__ import annotations

from math import isfinite

from backtest_engine import run_long_backtest, _validate_candles

POLICIES = ("baseline", "breakeven_1r", "partial_50_at_1r", "trailing_1r")


def _run_policy(candles, signals, policy, initial_balance=100.0,
                risk_percent=0.01, max_exposure_percent=0.95,
                fee_rate=0.001, slippage_rate=0.0005,
                stop_atr_multiple=1.2, reward_risk=2.0):
    if policy not in POLICIES[1:]:
        raise ValueError("Unknown alternative exit policy")
    _validate_candles(candles)
    params = (initial_balance, risk_percent, max_exposure_percent,
              fee_rate, slippage_rate, stop_atr_multiple, reward_risk)
    if not all(isfinite(float(x)) for x in params):
        raise ValueError("Backtest parameters must be finite")
    if initial_balance <= 0 or not 0 < risk_percent <= 1:
        raise ValueError("Invalid balance or risk")
    if not 0 < max_exposure_percent <= 1 or not 0 <= fee_rate < 1:
        raise ValueError("Invalid exposure or fee")
    if not 0 <= slippage_rate < 1 or stop_atr_multiple <= 0 or reward_risk <= 0:
        raise ValueError("Invalid slippage or stop/target multiple")

    index_by_timestamp = {int(c["timestamp"]): i for i, c in enumerate(candles)}
    signal_by_index = {}
    for signal in signals:
        timestamp = int(signal["timestamp"])
        if timestamp not in index_by_timestamp:
            raise ValueError(f"Signal candle missing: {timestamp}")
        index = index_by_timestamp[timestamp]
        if index >= len(candles) - 1:
            raise ValueError("No next candle for signal execution")
        if signal.get("side") != "BUY":
            raise ValueError("Only BUY signals are supported")
        atr = float(signal["atr"])
        if not isfinite(atr) or atr <= 0:
            raise ValueError("Invalid signal ATR")
        if index in signal_by_index:
            raise ValueError("Duplicate signal candle")
        signal_by_index[index] = atr

    cash = float(initial_balance)
    position = None
    trades = []
    equity_curve = []
    peak = float(initial_balance)
    max_drawdown = 0.0

    def execute_exit(pos, quantity, raw_price):
        price = raw_price * (1 - slippage_rate)
        proceeds = quantity * price
        fee = proceeds * fee_rate
        cash_delta = proceeds - fee
        pos["exit_proceeds_net"] += cash_delta
        pos["fees_paid"] += fee
        return cash_delta

    for i, candle in enumerate(candles):
        open_ = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        if position is None and i > 0 and (i - 1) in signal_by_index:
            atr = signal_by_index[i - 1]
            entry = open_ * (1 + slippage_rate)
            stop_distance = stop_atr_multiple * atr
            stop = entry - stop_distance
            target = entry + reward_risk * stop_distance
            risk_budget = cash * risk_percent
            risk_per_unit = (stop_distance + entry * fee_rate
                             + stop * (1 - slippage_rate) * fee_rate)
            qty_by_risk = risk_budget / risk_per_unit
            qty_by_exposure = (cash * max_exposure_percent) / (entry * (1 + fee_rate))
            qty_by_cash = cash / (entry * (1 + fee_rate))
            quantity = min(qty_by_risk, qty_by_exposure, qty_by_cash)
            if quantity > 0:
                entry_notional = quantity * entry
                entry_fee = entry_notional * fee_rate
                cash -= entry_notional + entry_fee
                position = {
                    "entry": entry, "initial_stop": stop, "stop": stop,
                    "target": target, "risk_distance": stop_distance,
                    "quantity": quantity, "remaining_quantity": quantity,
                    "entry_notional": entry_notional, "entry_fee": entry_fee,
                    "exit_proceeds_net": 0.0, "fees_paid": entry_fee,
                    "opened_at": int(candle["timestamp"]),
                    "partial_done": False, "highest_high": high,
                    "exit_reasons": [],
                }

        if position is not None:
            pos = position
            pos["highest_high"] = max(pos["highest_high"], high)
            reason = None
            raw_exit = None

            # Conservative ambiguity rule: an active stop takes precedence.
            if low <= pos["stop"]:
                raw_exit = min(open_, pos["stop"])
                reason = "stop_loss"
            elif high >= pos["target"]:
                raw_exit = max(open_, pos["target"])
                reason = "take_profit"

            if reason:
                cash += execute_exit(pos, pos["remaining_quantity"], raw_exit)
                net_pnl = pos["exit_proceeds_net"] - pos["entry_notional"] - pos["entry_fee"]
                trades.append({
                    "opened_at": pos["opened_at"], "closed_at": int(candle["timestamp"]),
                    "entry": pos["entry"], "stop": pos["initial_stop"],
                    "net_pnl": net_pnl, "reason": reason,
                    "fees_paid": pos["fees_paid"],
                })
                position = None
            else:
                if policy == "partial_50_at_1r" and not pos["partial_done"]:
                    level = pos["entry"] + pos["risk_distance"]
                    if high >= level:
                        partial_qty = pos["quantity"] * 0.5
                        cash += execute_exit(pos, partial_qty, max(open_, level))
                        pos["remaining_quantity"] -= partial_qty
                        pos["partial_done"] = True
                        pos["exit_reasons"].append("partial_1r")

                # Changes based on this candle's high are effective next candle.
                if policy == "breakeven_1r":
                    if high >= pos["entry"] + pos["risk_distance"]:
                        pos["stop"] = max(pos["stop"], pos["entry"])
                elif policy == "trailing_1r":
                    if high >= pos["entry"] + pos["risk_distance"]:
                        candidate = pos["highest_high"] - pos["risk_distance"]
                        pos["stop"] = max(pos["stop"], candidate)

                if i == len(candles) - 1:
                    raw_exit = close
                    cash += execute_exit(pos, pos["remaining_quantity"], raw_exit)
                    net_pnl = pos["exit_proceeds_net"] - pos["entry_notional"] - pos["entry_fee"]
                    trades.append({
                        "opened_at": pos["opened_at"], "closed_at": int(candle["timestamp"]),
                        "entry": pos["entry"], "stop": pos["initial_stop"],
                        "net_pnl": net_pnl, "reason": "end_of_data",
                        "fees_paid": pos["fees_paid"],
                    })
                    position = None

        equity = cash
        if position is not None:
            equity += position["remaining_quantity"] * close
        equity_curve.append({"timestamp": int(candle["timestamp"]), "equity": equity})
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    wins = sum(t["net_pnl"] > 0 for t in trades)
    gross_profit = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    gross_loss = -sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
    net_pnl = cash - float(initial_balance)
    return {
        "initial_balance": float(initial_balance), "final_equity": cash,
        "net_pnl": net_pnl, "return_percent": net_pnl / initial_balance * 100,
        "trade_count": len(trades),
        "win_rate_percent": wins / len(trades) * 100 if trades else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (
            None if not gross_profit else float("inf")),
        "max_drawdown_percent": max_drawdown * 100,
        "fees_paid": sum(t["fees_paid"] for t in trades),
        "trades": trades, "equity_curve": equity_curve,
    }


def _compact(result):
    trades = result["trades"]
    gross_profit = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    gross_loss = -sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
    return {
        "trade_count": result["trade_count"],
        "wins": sum(t["net_pnl"] > 0 for t in trades),
        "losses": sum(t["net_pnl"] < 0 for t in trades),
        "net_pnl": result["net_pnl"],
        "return_percent": result["return_percent"],
        "win_rate_percent": result["win_rate_percent"],
        "profit_factor": result["profit_factor"],
        "max_drawdown_percent": result["max_drawdown_percent"],
        "fees_paid": result["fees_paid"],
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
    }


def compare_exit_policies(candles, signals, initial_balance=100.0):
    """Return compact fold metrics for baseline and three exit alternatives."""
    results = {"baseline": run_long_backtest(
        candles, signals, initial_balance=initial_balance)}
    for policy in POLICIES[1:]:
        results[policy] = _run_policy(
            candles, signals, policy, initial_balance=initial_balance)
    return {name: _compact(result) for name, result in results.items()}


def aggregate_exit_policy_folds(fold_comparisons, initial_balance=100.0):
    """Aggregate independent folds without compounding capital across folds."""
    output = {}
    for policy in POLICIES:
        rows = [fold[policy] for fold in fold_comparisons]
        trades = sum(row["trade_count"] for row in rows)
        wins = sum(row["wins"] for row in rows)
        losses = sum(row["losses"] for row in rows)
        net = sum(row["net_pnl"] for row in rows)
        gp = sum(row["gross_profit"] for row in rows)
        gl = sum(row["gross_loss"] for row in rows)
        output[policy] = {
            "folds": len(rows),
            "trade_count": trades, "wins": wins, "losses": losses,
            "win_rate_percent": wins / trades * 100 if trades else 0.0,
            "profit_factor": gp / gl if gl else (None if not gp else float("inf")),
            "net_pnl_sum_of_independent_folds": net,
            "equal_allocation_return_percent": (
                net / (initial_balance * len(rows)) * 100 if rows else 0.0),
            "fees_paid": sum(row["fees_paid"] for row in rows),
            "worst_fold_max_drawdown_percent": max(
                (row["max_drawdown_percent"] for row in rows), default=0.0),
        }
    return output
