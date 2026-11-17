import json
from pathlib import Path
from datetime import datetime, timezone

INITIAL_BALANCE = 100.0
RISK_PERCENT = 0.01
MAX_POSITION_PERCENT = 0.30
MAX_AGGREGATE_RISK_PERCENT = 0.02
FEE_RATE = 0.001

# Separate ledger: never reuse or overwrite the original paper-trading state.
STATE_FILE = Path("data/paper_state_entry_context.json")


def load_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)
        state.setdefault("positions", {})
        state.setdefault("history", [])
        state.setdefault("signal_diagnostics", [])
        state.setdefault("last_processed_candle", {})
        state.setdefault("last_processed_close", {})
        return state
    return {
        "initial_balance": INITIAL_BALANCE,
        "cash_usdt": INITIAL_BALANCE,
        "positions": {},
        "history": [],
        "signal_diagnostics": [],
        "last_processed_candle": {},
        "last_processed_close": {},
    }


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)
    temp_file.replace(STATE_FILE)


def open_position(state, symbol, entry_price, stop_price, signal_diagnostic=None):
    entry_price = float(entry_price)
    stop_price = float(stop_price)
    if entry_price <= 0 or stop_price <= 0:
        return False, "Precio inválido"
    if stop_price >= entry_price:
        return False, "Stop inválido"
    if symbol in state["positions"]:
        return False, "Ya existe una posición abierta"

    balance = float(state["cash_usdt"])
    initial_balance = float(state["initial_balance"])
    if balance <= 0:
        return False, "Saldo insuficiente"

    risk_cap = initial_balance * MAX_AGGREGATE_RISK_PERCENT
    current_open_risk = sum(
        float(p.get("risk_budget", 0.0))
        for p in state["positions"].values()
    )
    remaining_risk = risk_cap - current_open_risk
    if remaining_risk <= 1e-12:
        return False, "Límite de riesgo agregado alcanzado"

    risk_amount = min(initial_balance * RISK_PERCENT, remaining_risk)
    risk_per_unit_with_fees = (
        entry_price - stop_price
        + entry_price * FEE_RATE
        + stop_price * FEE_RATE
    )
    quantity_by_risk = risk_amount / risk_per_unit_with_fees

    invested = sum(
        float(p["quantity"]) * float(p["entry_price"])
        for p in state["positions"].values()
    )
    max_total_investment = initial_balance * MAX_POSITION_PERCENT
    available_investment = max_total_investment - invested
    if available_investment <= 1e-12:
        return False, "Límite global de inversión alcanzado"

    quantity_by_balance = min(balance, available_investment) / (
        entry_price * (1 + FEE_RATE)
    )
    quantity = min(quantity_by_risk, quantity_by_balance)
    cost = quantity * entry_price
    entry_fee = cost * FEE_RATE
    actual_stop_risk = quantity * risk_per_unit_with_fees

    if quantity <= 0 or cost + entry_fee > balance + 1e-10:
        return False, "Saldo insuficiente"

    state["cash_usdt"] = max(0.0, balance - cost - entry_fee)
    state["positions"][symbol] = {
        "entry_price": entry_price,
        "stop_price": stop_price,
        "quantity": quantity,
        "entry_fee": entry_fee,
        "risk_budget": actual_stop_risk,
        "risk_budget_target": risk_amount,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "signal_diagnostic": signal_diagnostic,
    }
    save_state(state)
    return True, (
        f"Compra simulada: {symbol} | Riesgo estimado al stop: "
        f"{actual_stop_risk:.4f} USDT (objetivo: {risk_amount:.4f} USDT)"
    )


def close_position(state, symbol, exit_price, reason="manual"):
    position = state["positions"].get(symbol)
    if not position:
        return False, "No existe posición abierta"
    exit_price = float(exit_price)
    if exit_price <= 0:
        return False, "Precio inválido"

    quantity = float(position["quantity"])
    proceeds = quantity * exit_price
    exit_fee = proceeds * FEE_RATE
    state["cash_usdt"] += proceeds - exit_fee
    pnl = (
        proceeds - exit_fee
        - quantity * float(position["entry_price"])
        - float(position.get("entry_fee", 0.0))
    )
    trade = {
        **position,
        "symbol": symbol,
        "exit_price": exit_price,
        "exit_fee": exit_fee,
        "net_pnl": pnl,
        "reason": reason,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }
    state["history"].append(trade)
    del state["positions"][symbol]
    save_state(state)
    return True, f"Resultado neto: {pnl:.4f} USDT"


def get_status(state, market_prices=None):
    market_prices = market_prices or {}
    invested = 0.0
    market_value = 0.0
    unrealized_pnl = 0.0
    open_risk = 0.0

    for symbol, position in state.get("positions", {}).items():
        quantity = float(position["quantity"])
        entry = float(position["entry_price"])
        mark = float(market_prices.get(
            symbol, state.get("last_processed_close", {}).get(symbol, entry)
        ))
        invested += quantity * entry
        market_value += quantity * mark
        estimated_exit_fee = quantity * mark * FEE_RATE
        unrealized_pnl += (
            quantity * mark - quantity * entry
            - float(position.get("entry_fee", 0.0)) - estimated_exit_fee
        )
        open_risk += float(position.get("risk_budget", 0.0))

    cash = float(state["cash_usdt"])
    initial = float(state["initial_balance"])
    realized = sum(float(t["net_pnl"]) for t in state.get("history", []))
    equity = cash + market_value - sum(
        float(p["quantity"]) * float(market_prices.get(
            symbol, state.get("last_processed_close", {}).get(
                symbol, p["entry_price"]
            )
        )) * FEE_RATE
        for symbol, p in state.get("positions", {}).items()
    )
    return {
        "initial_balance": round(initial, 4),
        "cash_usdt": round(cash, 4),
        "invested_usdt": round(invested, 4),
        "market_value_usdt": round(market_value, 4),
        "equity_usdt": round(equity, 4),
        "realized_pnl": round(realized, 4),
        "unrealized_pnl": round(unrealized_pnl, 4),
        "total_pnl": round(equity - initial, 4),
        "open_risk_usdt": round(open_risk, 4),
        "open_risk_limit_usdt": round(initial * MAX_AGGREGATE_RISK_PERCENT, 4),
        "investment_limit_usdt": round(initial * MAX_POSITION_PERCENT, 4),
        "open_positions": len(state.get("positions", {})),
        "closed_trades": len(state.get("history", [])),
        "signals_recorded": len(state.get("signal_diagnostics", [])),
    }


if __name__ == "__main__":
    state = load_state()
    print(json.dumps(get_status(state), indent=2))
