import json
from pathlib import Path
from datetime import datetime, timezone

INITIAL_BALANCE = 100.0
RISK_PERCENT = 0.01
MAX_POSITION_PERCENT = 0.95
FEE_RATE = 0.001

STATE_FILE = Path("data/paper_state.json")


def load_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)

        state.setdefault("positions", {})
        state.setdefault("history", [])
        state.setdefault("last_processed_candle", {})
        return state

    return {
        "initial_balance": INITIAL_BALANCE,
        "cash_usdt": INITIAL_BALANCE,
        "positions": {},
        "history": [],
        "last_processed_candle": {}
    }


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    temp_file.replace(STATE_FILE)


def open_position(state, symbol, entry_price, stop_price, persist=True):
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

    risk_amount = initial_balance * RISK_PERCENT
    risk_per_unit = entry_price - stop_price

    risk_per_unit_with_fees = (
        risk_per_unit
        + entry_price * FEE_RATE
        + stop_price * FEE_RATE
    )

    quantity_by_risk = (
        risk_amount / risk_per_unit_with_fees
    )

    invested = sum(
        p["quantity"] * p["entry_price"]
        for p in state["positions"].values()
    )

    max_total_investment = (
        initial_balance * MAX_POSITION_PERCENT
    )

    available_investment = (
        max_total_investment - invested
    )

    if available_investment <= 0:
        return False, "Límite global de inversión alcanzado"

    quantity_by_balance = (
        min(balance, available_investment)
        / (entry_price * (1 + FEE_RATE))
    )

    quantity = min(
        quantity_by_risk,
        quantity_by_balance
    )

    cost = quantity * entry_price
    entry_fee = cost * FEE_RATE

    if quantity <= 0 or cost + entry_fee > balance:
        return False, "Saldo insuficiente"

    state["cash_usdt"] -= cost + entry_fee

    state["positions"][symbol] = {
        "entry_price": entry_price,
        "stop_price": stop_price,
        "quantity": quantity,
        "entry_fee": entry_fee,
        "risk_budget": risk_amount,
        "opened_at": datetime.now(timezone.utc).isoformat()
    }

    if persist:
        save_state(state)

    return True, (
        f"Compra simulada: {symbol} | "
        f"Riesgo presupuestado: {risk_amount:.4f} USDT"
    )


def close_position(state, symbol, exit_price, reason="manual", persist=True):
    position = state["positions"].get(symbol)

    if not position:
        return False, "No existe posición abierta"

    exit_price = float(exit_price)

    if exit_price <= 0:
        return False, "Precio inválido"

    quantity = position["quantity"]
    proceeds = quantity * exit_price
    exit_fee = proceeds * FEE_RATE

    state["cash_usdt"] += proceeds - exit_fee

    pnl = (
        proceeds - exit_fee
        - quantity * position["entry_price"]
        - position["entry_fee"]
    )

    trade = {
        **position,
        "symbol": symbol,
        "exit_price": exit_price,
        "exit_fee": exit_fee,
        "net_pnl": pnl,
        "reason": reason,
        "closed_at": datetime.now(timezone.utc).isoformat()
    }

    state["history"].append(trade)
    del state["positions"][symbol]

    if persist:
        save_state(state)

    return True, f"Resultado neto: {pnl:.4f} USDT"


def get_status(state):
    invested = sum(
        p["quantity"] * p["entry_price"]
        for p in state["positions"].values()
    )

    return {
        "initial_balance": state["initial_balance"],
        "cash_usdt": round(state["cash_usdt"], 4),
        "invested_usdt": round(invested, 4),
        "open_positions": len(state["positions"]),
        "closed_trades": len(state["history"]),
        "realized_pnl": round(
            sum(t["net_pnl"] for t in state["history"]), 4
        )
    }


if __name__ == "__main__":
    state = load_state()
    print(json.dumps(get_status(state), indent=2))
