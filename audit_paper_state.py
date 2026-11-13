"""Read-only audit of the paper-trading state. Never places trades or writes files."""
import json
from pathlib import Path

STATE_PATH = Path("data/paper_state.json")
RISK_PERCENT = 0.01
MAX_POSITION_PERCENT = 0.95
FEE_RATE = 0.001


def main():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    initial = float(state["initial_balance"])
    cash = float(state["cash_usdt"])
    positions = state.get("positions", {})
    history = state.get("history", [])

    invested = sum(
        float(p["quantity"]) * float(p["entry_price"])
        for p in positions.values()
    )
    exposure_pct = invested / initial * 100 if initial else 0.0
    risk_limit = initial * RISK_PERCENT

    print("READ-ONLY PAPER STATE AUDIT")
    print(f"Initial balance: {initial:.8f} USDT")
    print(f"Cash: {cash:.8f} USDT")
    print(f"Open investment: {invested:.8f} USDT")
    print(f"Exposure: {exposure_pct:.4f}% (limit {MAX_POSITION_PERCENT * 100:.2f}%)")
    print(f"Open positions: {len(positions)}")
    print(f"Closed trades: {len(history)}")
    print(f"Realized PnL: {sum(float(t['net_pnl']) for t in history):.8f} USDT")
    print(f"Per-position risk ceiling: {risk_limit:.8f} USDT")

    failures = []
    if invested > initial * MAX_POSITION_PERCENT + 1e-9:
        failures.append("Global exposure exceeds 95%.")

    for symbol, p in positions.items():
        entry = float(p["entry_price"])
        stop = float(p["stop_price"])
        qty = float(p["quantity"])
        entry_fee = float(p.get("entry_fee", 0.0))
        stop_exit_fee = qty * stop * FEE_RATE
        stop_loss_estimate = qty * (entry - stop) + entry_fee + stop_exit_fee
        stored_budget = float(p.get("risk_budget", 0.0))

        print(f"{symbol}: stop-loss estimate incl. fees={stop_loss_estimate:.8f} USDT; "
              f"stored risk_budget={stored_budget:.8f} USDT")

        if stop_loss_estimate > risk_limit + 1e-9:
            failures.append(f"{symbol} estimated stop risk exceeds 1% of initial balance.")
        if stored_budget > risk_limit + 1e-9:
            failures.append(f"{symbol} stored risk_budget exceeds the 1% ceiling.")

    if failures:
        print("AUDIT: FAIL")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("AUDIT: PASS (limits checked against current stored state only)")
    print("Note: this audit does not validate stale candles, market prices, or execution history.")


if __name__ == "__main__":
    main()
