"""Read-only integrity checks for the isolated paper-trading ledger."""

import json
from pathlib import Path

STATE_FILE = Path("data/paper_state_entry_context.json")
TOLERANCE = 1e-8


def audit_state(state):
    """Return ledger integrity findings without mutating state or placing trades."""
    issues = []
    initial = float(state.get("initial_balance", 0.0))
    cash = float(state.get("cash_usdt", 0.0))
    positions = state.get("positions", {})
    history = state.get("history", [])

    if initial <= 0:
        issues.append("initial_balance must be positive")
    if cash < -TOLERANCE:
        issues.append("cash_usdt is negative")

    invested = 0.0
    open_risk = 0.0
    entry_fees_open = 0.0
    for symbol, position in positions.items():
        try:
            quantity = float(position["quantity"])
            entry = float(position["entry_price"])
            stop = float(position["stop_price"])
            fee = float(position.get("entry_fee", 0.0))
            risk = float(position.get("risk_budget", 0.0))
        except (KeyError, TypeError, ValueError):
            issues.append(f"{symbol}: missing or invalid position fields")
            continue
        if quantity <= 0 or entry <= 0 or stop <= 0 or stop >= entry:
            issues.append(f"{symbol}: invalid quantity or price/stop relationship")
        if fee < -TOLERANCE or risk < -TOLERANCE:
            issues.append(f"{symbol}: negative fee or risk budget")
        invested += quantity * entry
        entry_fees_open += fee
        open_risk += risk

    if initial > 0 and invested > initial * 0.30 + TOLERANCE:
        issues.append("open investment exceeds the 30% portfolio limit")
    if initial > 0 and open_risk > initial * 0.02 + TOLERANCE:
        issues.append("aggregate open risk exceeds the 2% portfolio limit")

    closed_entry_cost_and_fees = 0.0
    closed_proceeds = 0.0
    realized_pnl = 0.0
    fees_closed = 0.0
    for index, trade in enumerate(history):
        try:
            quantity = float(trade["quantity"])
            entry = float(trade["entry_price"])
            exit_price = float(trade["exit_price"])
            entry_fee = float(trade.get("entry_fee", 0.0))
            exit_fee = float(trade.get("exit_fee", 0.0))
            recorded_pnl = float(trade["net_pnl"])
        except (KeyError, TypeError, ValueError):
            issues.append(f"closed trade {index}: missing or invalid accounting fields")
            continue
        if quantity <= 0 or entry <= 0 or exit_price <= 0:
            issues.append(f"closed trade {index}: non-positive quantity or price")
        if entry_fee < -TOLERANCE or exit_fee < -TOLERANCE:
            issues.append(f"closed trade {index}: negative commission")
        expected_pnl = quantity * (exit_price - entry) - entry_fee - exit_fee
        if abs(recorded_pnl - expected_pnl) > TOLERANCE:
            issues.append(f"closed trade {index}: net PnL does not reconcile")
        closed_entry_cost_and_fees += quantity * entry + entry_fee
        closed_proceeds += quantity * exit_price - exit_fee
        realized_pnl += recorded_pnl
        fees_closed += entry_fee + exit_fee

    expected_cash = (
        initial - invested - entry_fees_open
        - closed_entry_cost_and_fees + closed_proceeds
    )
    cash_difference = cash - expected_cash
    if abs(cash_difference) > TOLERANCE:
        issues.append("cash balance does not reconcile with ledger transactions")

    return {
        "valid": not issues,
        "issues": issues,
        "initial_balance_usdt": round(initial, 8),
        "cash_usdt": round(cash, 8),
        "open_investment_usdt": round(invested, 8),
        "open_risk_usdt": round(open_risk, 8),
        "closed_trades": len(history),
        "open_positions": len(positions),
        "realized_pnl_usdt": round(realized_pnl, 8),
        "closed_fees_usdt": round(fees_closed, 8),
        "expected_cash_usdt": round(expected_cash, 8),
        "cash_difference_usdt": round(cash_difference, 8),
    }



def main():
    with STATE_FILE.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    report = audit_state(state)
    print(json.dumps(report, indent=2))
    if not report["valid"]:
        raise SystemExit("Paper ledger integrity audit failed.")


if __name__ == "__main__":
    main()
