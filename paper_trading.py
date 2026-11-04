
import json
import os
from pathlib import Path
from datetime import datetime, timezone

INITIAL_BALANCE = 100.0
RISK_PERCENT = 0.01
FEE_RATE = 0.001
STATE_FILE = Path("data/paper_state.json")


def load_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)

    return {
        "initial_balance": INITIAL_BALANCE,
        "cash_usdt": INITIAL_BALANCE,
        "positions": {},
        "history": []
    }


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    temp_file.replace(STATE_FILE)


def open_position(state, symbol, entry_price, stop_price):
    if entry_price <= 0 or stop_price <= 0:
        return False, "Precio inválido"

    if stop_price >= entry_price:
        return False, "En Spot, el stop debe estar debajo de la entrada"

    if symbol in state["positions"]:
        return False, "Ya existe una posición para este par"

    risk_amount = state["cash_usdt"] * RISK_PERCENT
    quantity = risk_amount / (entry_price - stop_price)

    # Reservamos margen para la comisión de compra.
    cost = quantity * entry_price
    fee = cost * FEE_RATE

    if cost + fee > state["cash_usdt"]:
        quantity = state["cash_usdt"] / (
            entry_price * (1 + FEE_RATE)
        )
        cost = quantity * entry_price
        fee = cost * FEE_RATE

    if quantity <= 0 or cost + fee > state["cash_usdt"]:
        return False, "Saldo insuficiente"

    state["cash_usdt"] -= cost + fee

    state["positions"][symbol] = {
        "entry_price": entry_price,
        "stop_price": stop_price,
        "quantity": quantity,
        "entry_fee": fee,
        "opened_at": datetime.now(timezone.utc).isoformat()
    }

    save_state(state)
    return True, f"Compra simulada de {symbol}: {quantity:.8f}"


def close_position(state, symbol, exit_price, reason="manual"):
    position = state["positions"].get(symbol)

    if not position:
        return False, "No existe una posición abierta"

    if exit_price <= 0:
        return False, "Precio de salida inválido"

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

    save_state(state)
    return True, f"Operación cerrada. Resultado neto: {pnl:.4f} USDT"


def get_status(state):
    invested = sum(
        p["quantity"] * p["entry_price"]
        for p in state["positions"].values()
    )

    return {
        "initial_balance": state["initial_balance"],
        "cash_usdt": state["cash_usdt"],
        "invested_usdt": invested,
        "open_positions": len(state["positions"]),
        "closed_trades": len(state["history"]),
        "realized_pnl": sum(
            trade["net_pnl"] for trade in state["history"]
        )
    }


if __name__ == "__main__":
    state = load_state()
    print(json.dumps(get_status(state), indent=2))
