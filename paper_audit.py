import json
from pathlib import Path


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

    open_cost = sum(
        float(position["quantity"]) * float(position["entry_price"])
        + float(position.get("entry_fee", 0.0))
        for position in positions.values()
    )
    # Closed-trade net PnL already includes both entry and exit fees.
    # Only open positions remain tied up in cash as cost plus entry fee.
    expected_cash = initial + net_pnl - open_cost
    cash_difference = cash - expected_cash

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
        "pnl_mismatches": pnl_mismatches,
        "equity_curve": equity_curve,
        "limitations": [
            "Drawdown is calculated from closed trades only; intratrade drawdown is unavailable.",
            "Open positions are not marked to market; cash is not total account equity.",
            "A small trade sample is not evidence of a durable trading edge.",
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
