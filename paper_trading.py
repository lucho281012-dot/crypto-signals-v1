
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


def open_position(state, symbol, entry_price, stop_price):
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

    # Riesgo fijo: 1% del capital inicial
    risk_amount = initial_balance * RISK_PERCENT

    risk_per_unit = entry_price - stop_price

    # Incluye comisiones estimadas de entrada y salida
    risk_per_unit_with_fees = (
        risk_per_unit
        + entry_price * FEE_RATE
        + stop_price * FEE_RATE
    )

    quantity_by_risk = (
        risk_amount / risk_per_unit_with_fees
    )

    # Calcula toda la inversión actualmente abierta
    invested = sum(
        p["quantity"] * p["entry_price"]
        for p in state["positions"].values()
    )

    # Límite global del 95% del capital inicial
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

    save_state(state)

    return True, (
        f"Compra simulada: {symbol} | "
        f"Riesgo presupuestado: {risk_amount:.4f} USDT"
    )


