import json
from pathlib import Path
from datetime import datetime

from paper_trading import (
    calculate_open_risk,
    risk_per_unit,
    RISK_PERCENT,
    MAX_POSITION_PERCENT,
    MIN_NOTIONAL_USDT,
)


STATE_FILE = Path("data/paper_state.json")
TOLERANCE = 1e-8


def build_audit(state):
    initial = float(state["initial_balance"])
    cash = float(state["cash_usdt"])
    history = list(state.get("history", []))
    positions = state.get("positions", {})

    pnls = [float(trade["net_pnl"]) for trade in history]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    net_pnl = sum(pnls)

    equity = initial
    peak = initial
    max_drawdown = 0.0
    equity_curve = []
    for trade, pnl in zip(history, pnls):
        equity += pnl
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        equity_curve.append({
            "symbol": trade.get("symbol", "UNKNOWN"),
            "closed_at": trade.get("closed_at"),
            "net_pnl": round(pnl, 10),
            "equity": round(equity, 10),
        })

    total_fees = sum(
        float(trade.get("entry_fee", 0.0))
        + float(trade.get("exit_fee", 0.0))
        for trade in history
    )
    total_fees += sum(
        float(position.get("entry_fee", 0.0))
        for position in positions.values()
    )

    pnl_mismatches = []
    risk_analysis = []
    symbol_stats = {}

    for index, trade in enumerate(history):
        quantity = float(trade["quantity"])
        entry = float(trade["entry_price"])
        exit_price = float(trade["exit_price"])
        entry_fee = float(trade.get("entry_fee", 0.0))
        exit_fee = float(trade.get("exit_fee", 0.0))
        recomputed = quantity * (exit_price - entry) - entry_fee - exit_fee
        recorded = float(trade["net_pnl"])
        difference = recorded - recomputed
        if abs(difference) > TOLERANCE:
            pnl_mismatches.append({
                "trade_index": index,
                "symbol": trade.get("symbol"),
                "recorded_net_pnl": recorded,
                "recomputed_net_pnl": recomputed,
                "difference": difference,
            })

        stop = float(trade.get("stop_price", 0.0))
        estimated_stop_loss = None
        risk_percent = None
        r_multiple = None
        if stop > 0 and entry > stop and quantity > 0:
            estimated_stop_loss = quantity * risk_per_unit(entry, stop)
            risk_percent = estimated_stop_loss / initial * 100 if initial else None
            r_multiple = recorded / estimated_stop_loss if estimated_stop_loss > 0 else None

        risk_analysis.append({
            "symbol": trade.get("symbol", "UNKNOWN"),
            "estimated_loss_at_stop_usdt": round(estimated_stop_loss, 8) if estimated_stop_loss is not None else None,
            "risk_percent_of_initial_balance": round(risk_percent, 6) if risk_percent is not None else None,
            "realized_r_multiple": round(r_multiple, 6) if r_multiple is not None else None,
            "recorded_actual_risk_budget_usdt": round(float(trade.get("risk_budget", 0.0)), 8),
            "risk_budget_target_usdt": round(float(trade.get("risk_budget_target", 0.0)), 8),
        })

        symbol = trade.get("symbol", "UNKNOWN")
        bucket = symbol_stats.setdefault(symbol, {
            "trades": 0, "wins": 0, "losses": 0,
            "net_pnl_usdt": 0.0, "gross_profit_usdt": 0.0,
            "gross_loss_usdt": 0.0, "fees_usdt": 0.0,
        })
        bucket["trades"] += 1
        bucket["net_pnl_usdt"] += recorded
        bucket["fees_usdt"] += entry_fee + exit_fee
        if recorded > 0:
            bucket["wins"] += 1
            bucket["gross_profit_usdt"] += recorded
        elif recorded < 0:
            bucket["losses"] += 1
            bucket["gross_loss_usdt"] += -recorded

    for bucket in symbol_stats.values():
        bucket["win_rate_percent"] = round(bucket["wins"] / bucket["trades"] * 100, 4)
        bucket["profit_factor"] = (
            round(bucket["gross_profit_usdt"] / bucket["gross_loss_usdt"], 6)
            if bucket["gross_loss_usdt"] > 0 else None
        )
        for key in ("net_pnl_usdt", "gross_profit_usdt", "gross_loss_usdt", "fees_usdt"):
            bucket[key] = round(bucket[key], 8)

    open_cost = sum(
        float(position["quantity"]) * float(position["entry_price"])
        + float(position.get("entry_fee", 0.0))
        for position in positions.values()
    )
    # Closed-trade net PnL already includes both entry and exit fees.
    # Only open positions remain tied up in cash as cost plus entry fee.
    expected_cash = initial + net_pnl - open_cost
    cash_difference = cash - expected_cash

    # Recompute current portfolio risk from quantity/entry/stop. Never trust
    # the historical risk_budget field as the source of truth.
    open_risk_error = None
    try:
        open_risk = calculate_open_risk(state)
    except RuntimeError as error:
        open_risk = None
        open_risk_error = str(error)

    open_exposure = sum(
        float(position.get("quantity", 0.0))
        * float(position.get("entry_price", 0.0))
        for position in positions.values()
    )
    risk_limit = initial * RISK_PERCENT
    exposure_limit = initial * MAX_POSITION_PERCENT

    records = list(history) + [
        {**position, "symbol": symbol, "_is_open": True}
        for symbol, position in positions.items()
    ]
    notionals = []
    trace_required = (
        "signal_candle_timestamp", "signal_confirmed_at",
        "entry_decision_at", "entry_candle_timestamp",
        "quote_timestamp", "quote_price", "quote_side", "entry_delay_seconds",
        "strategy_version", "signal_snapshot",
    )
    traceable_records = 0
    for record in records:
        try:
            notional = float(record["quantity"]) * float(record["entry_price"])
            notionals.append(notional)
            if all(record.get(key) is not None for key in trace_required):
                traceable_records += 1
        except (KeyError, TypeError, ValueError):
            continue

    # Reconstruct peak historical risk/exposure from entry and exit timestamps.
    # Close events sort before opens at the same timestamp.
    events = []
    historical_complete = True
    for record in records:
        try:
            quantity = float(record["quantity"])
            entry = float(record["entry_price"])
            stop = float(record["stop_price"])
            opened = datetime.fromisoformat(str(record["opened_at"])).timestamp()
            position_risk = quantity * risk_per_unit(entry, stop)
            notional = quantity * entry
            events.append((opened, 1, position_risk, notional))
            if not record.get("_is_open"):
                closed = datetime.fromisoformat(str(record["closed_at"])).timestamp()
                events.append((closed, 0, -position_risk, -notional))
        except (KeyError, TypeError, ValueError):
            historical_complete = False

    peak_risk = 0.0
    peak_exposure = 0.0
    running_risk = 0.0
    running_exposure = 0.0
    if historical_complete:
        for _, _, risk_delta, exposure_delta in sorted(events):
            running_risk += risk_delta
            running_exposure += exposure_delta
            peak_risk = max(peak_risk, running_risk)
            peak_exposure = max(peak_exposure, running_exposure)
    else:
        peak_risk = None
        peak_exposure = None

    dust_count = sum(1 for value in notionals if value < MIN_NOTIONAL_USDT)
    below_one_count = sum(1 for value in notionals if value < 1.0)
    below_ten_count = sum(1 for value in notionals if value < 10.0)
    trace_total = len(records)

    return {
        "initial_balance": round(initial, 8),
        "cash_usdt": round(cash, 8),
        "open_positions": len(positions),
        "closed_trades": len(history),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_percent": round(len(wins) / len(history) * 100, 4) if history else None,
        "gross_profit_usdt": round(gross_profit, 8),
        "gross_loss_usdt": round(gross_loss, 8),
        "net_realized_pnl_usdt": round(net_pnl, 8),
        "return_percent": round(net_pnl / initial * 100, 4) if initial else None,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "average_win_usdt": round(gross_profit / len(wins), 8) if wins else None,
        "average_loss_usdt": round(-gross_loss / len(losses), 8) if losses else None,
        "expectancy_usdt_per_trade": round(net_pnl / len(history), 8) if history else None,
        "max_closed_trade_drawdown_percent": round(max_drawdown * 100, 6),
        "total_fees_usdt": round(total_fees, 8),
        "expected_cash_usdt": round(expected_cash, 8),
        "cash_reconciliation_difference_usdt": round(cash_difference, 10),
        "cash_reconciles": abs(cash_difference) <= TOLERANCE,
        "portfolio_limits": {
            "open_risk_usdt": round(open_risk, 8) if open_risk is not None else None,
            "open_risk_limit_usdt": round(risk_limit, 8),
            "open_risk_within_limit": (
                open_risk is not None and open_risk <= risk_limit + TOLERANCE
            ),
            "open_risk_error": open_risk_error,
            "open_exposure_usdt": round(open_exposure, 8),
            "open_exposure_limit_usdt": round(exposure_limit, 8),
            "open_exposure_within_limit": open_exposure <= exposure_limit + TOLERANCE,
            "historical_peak_risk_usdt": round(peak_risk, 8) if peak_risk is not None else None,
            "historical_peak_exposure_usdt": round(peak_exposure, 8) if peak_exposure is not None else None,
            "historical_reconstruction_complete": historical_complete,
        },
        "position_size_audit": {
            "records_checked": trace_total,
            "below_minimum_notional_count": dust_count,
            "below_one_usdt_count": below_one_count,
            "below_ten_usdt_count": below_ten_count,
            "minimum_notional_usdt": MIN_NOTIONAL_USDT,
        },
        "execution_traceability": {
            "records_with_complete_entry_metadata": traceable_records,
            "records_checked": trace_total,
            "coverage_percent": round(traceable_records / trace_total * 100, 4) if trace_total else None,
        },
        "pnl_mismatches": pnl_mismatches,
        "risk_analysis_per_trade": risk_analysis,
        "performance_by_symbol": symbol_stats,
        "equity_curve": equity_curve,
        "limitations": [
            "Drawdown is calculated from closed trades only; intratrade drawdown is unavailable.",
            "Open positions are not marked to market; cash is not total account equity.",
            "A small trade sample is not evidence of a durable trading edge.",
            "Legacy entries without quote timestamps and signal snapshots cannot be fully execution-audited.",
            "Historical peak portfolio risk is unknown when any trade lacks valid entry/exit timestamps or stop data.",
        ],
    }


def main():
    with STATE_FILE.open("r", encoding="utf-8") as file:
        state = json.load(file)
    report = build_audit(state)
    print(json.dumps(report, indent=2))
    if not report["cash_reconciles"] or report["pnl_mismatches"]:
        raise SystemExit("Paper ledger audit failed: accounting mismatch detected.")


if __name__ == "__main__":
    main()
