"""Read-only integrity checks for the isolated paper-trading ledger."""

import json
import math
from pathlib import Path

from paper_trading import FEE_RATE

STATE_FILE = Path("data/paper_state_entry_context.json")
TOLERANCE = 1e-8


def _finite_number(value):
    """Return a finite float, or None for malformed/non-finite values."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def audit_state(state):
    """Return ledger integrity findings without mutating state or placing trades."""
    issues = []
    if not isinstance(state, dict):
        return {
            "valid": False,
            "issues": ["ledger must be a JSON object"],
            "closed_trades": 0,
            "open_positions": 0,
        }

    initial = _finite_number(state.get("initial_balance"))
    cash = _finite_number(state.get("cash_usdt"))
    if initial is None:
        issues.append("initial_balance must be a finite number")
        initial = 0.0
    elif initial <= 0:
        issues.append("initial_balance must be positive")
    if cash is None:
        issues.append("cash_usdt must be a finite number")
        cash = 0.0
    elif cash < -TOLERANCE:
        issues.append("cash_usdt is negative")

    positions = state.get("positions", {})
    history = state.get("history", [])
    last_prices = state.get("last_processed_close", {})
    if not isinstance(positions, dict):
        issues.append("positions must be an object")
        positions = {}
    if not isinstance(history, list):
        issues.append("history must be a list")
        history = []
    if not isinstance(last_prices, dict):
        issues.append("last_processed_close must be an object")
        last_prices = {}

    invested = 0.0
    open_risk = 0.0
    entry_fees_open = 0.0
    market_value = 0.0
    estimated_exit_fees = 0.0
    unrealized_pnl = 0.0

    for symbol, position in positions.items():
        if not isinstance(position, dict):
            issues.append(f"{symbol}: position must be an object")
            continue
        quantity = _finite_number(position.get("quantity"))
        entry = _finite_number(position.get("entry_price"))
        stop = _finite_number(position.get("stop_price"))
        fee = _finite_number(position.get("entry_fee", 0.0))
        risk = _finite_number(position.get("risk_budget", 0.0))
        if any(value is None for value in (quantity, entry, stop, fee, risk)):
            issues.append(f"{symbol}: missing, malformed, or non-finite position fields")
            continue
        if quantity <= 0 or entry <= 0 or stop <= 0 or stop >= entry:
            issues.append(f"{symbol}: invalid quantity or price/stop relationship")
        if fee < -TOLERANCE or risk < -TOLERANCE:
            issues.append(f"{symbol}: negative fee or risk budget")

        raw_mark = last_prices.get(symbol, entry)
        mark = _finite_number(raw_mark)
        if mark is None or mark <= 0:
            issues.append(f"{symbol}: invalid or non-finite mark price")
            mark = entry

        position_market_value = quantity * mark
        exit_fee_estimate = position_market_value * FEE_RATE
        invested += quantity * entry
        entry_fees_open += fee
        open_risk += risk
        market_value += position_market_value
        estimated_exit_fees += exit_fee_estimate
        unrealized_pnl += (
            position_market_value - quantity * entry - fee - exit_fee_estimate
        )

    if initial > 0 and invested > initial * 0.30 + TOLERANCE:
        issues.append("open investment exceeds the 30% portfolio limit")
    if initial > 0 and open_risk > initial * 0.02 + TOLERANCE:
        issues.append("aggregate open risk exceeds the 2% portfolio limit")

    closed_entry_cost_and_fees = 0.0
    closed_proceeds = 0.0
    realized_pnl = 0.0
    fees_closed = 0.0
    seen_trades = set()

    for index, trade in enumerate(history):
        if not isinstance(trade, dict):
            issues.append(f"closed trade {index}: trade must be an object")
            continue
        # Exact full-record duplicates are safe to flag; weaker fingerprints
        # could incorrectly classify two legitimate trades as duplicates.
        try:
            fingerprint = json.dumps(
                trade, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError):
            issues.append(f"closed trade {index}: contains non-JSON or non-finite data")
            fingerprint = None
        if fingerprint is not None:
            if fingerprint in seen_trades:
                issues.append(f"closed trade {index}: exact duplicate history record")
            seen_trades.add(fingerprint)

        quantity = _finite_number(trade.get("quantity"))
        entry = _finite_number(trade.get("entry_price"))
        exit_price = _finite_number(trade.get("exit_price"))
        entry_fee = _finite_number(trade.get("entry_fee", 0.0))
        exit_fee = _finite_number(trade.get("exit_fee", 0.0))
        recorded_pnl = _finite_number(trade.get("net_pnl"))
        if any(value is None for value in (
            quantity, entry, exit_price, entry_fee, exit_fee, recorded_pnl
        )):
            issues.append(
                f"closed trade {index}: missing, malformed, or non-finite accounting fields"
            )
            continue
        if quantity <= 0 or entry <= 0 or exit_price <= 0:
            issues.append(f"closed trade {index}: non-positive quantity or price")
        if entry_fee < -TOLERANCE or exit_fee < -TOLERANCE:
            issues.append(f"closed trade {index}: negative commission")

        expected_pnl = quantity * (exit_price - entry) - entry_fee - exit_fee
        if not math.isfinite(expected_pnl):
            issues.append(f"closed trade {index}: accounting calculation is non-finite")
            continue
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
    if not math.isfinite(expected_cash) or not math.isfinite(cash_difference):
        issues.append("cash reconciliation calculation is non-finite")
        expected_cash = 0.0
        cash_difference = 0.0
    elif abs(cash_difference) > TOLERANCE:
        issues.append("cash balance does not reconcile with ledger transactions")

    equity = cash + market_value - estimated_exit_fees
    total_pnl = equity - initial
    equity_difference = total_pnl - (realized_pnl + unrealized_pnl)
    if not all(math.isfinite(value) for value in (
        equity, total_pnl, equity_difference, realized_pnl, unrealized_pnl
    )):
        issues.append("equity reconciliation calculation is non-finite")
        equity = total_pnl = equity_difference = 0.0
    elif abs(equity_difference) > TOLERANCE:
        issues.append("equity does not reconcile with realized and unrealized PnL")

    return {
        "valid": not issues,
        "issues": issues,
        "initial_balance_usdt": round(initial, 8),
        "cash_usdt": round(cash, 8),
        "equity_usdt": round(equity, 8),
        "realized_pnl_usdt": round(realized_pnl, 8),
        "unrealized_pnl_usdt": round(unrealized_pnl, 8),
        "total_pnl_usdt": round(total_pnl, 8),
        "equity_difference_usdt": round(equity_difference, 8),
        "open_investment_usdt": round(invested, 8),
        "open_risk_usdt": round(open_risk, 8),
        "closed_trades": len(history),
        "open_positions": len(positions),
        "closed_fees_usdt": round(fees_closed, 8),
        "expected_cash_usdt": round(expected_cash, 8),
        "cash_difference_usdt": round(cash_difference, 8),
    }


def main():
    with STATE_FILE.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    report = audit_state(state)
    print(json.dumps(report, indent=2, allow_nan=False))
    if not report["valid"]:
        raise SystemExit("Paper ledger integrity audit failed.")


if __name__ == "__main__":
    main()
