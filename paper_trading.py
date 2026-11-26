import json
import math
from pathlib import Path
from datetime import datetime, timezone

INITIAL_BALANCE = 100.0
RISK_PERCENT = 0.01
MAX_POSITION_PERCENT = 0.95
FEE_RATE = 0.001
STATE_FILE = Path("data/paper_state.json")
TOLERANCE = 1e-10


def load_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)
        state.setdefault("positions", {})
        state.setdefault("history", [])
        state.setdefault("last_processed_candle", {})
        state.setdefault("last_processed_close", {})
        return state
    return {"initial_balance": INITIAL_BALANCE, "cash_usdt": INITIAL_BALANCE,
            "positions": {}, "history": [], "last_processed_candle": {},
            "last_processed_close": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)
    temp_file.replace(STATE_FILE)


def _positive(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} inválido")
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} inválido")
    return number


def _risk_per_unit(entry, stop):
    return entry - stop + entry * FEE_RATE + stop * FEE_RATE


def _position_risk(position):
    qty = _positive(position["quantity"], "Cantidad de posición")
    entry = _positive(position["entry_price"], "Entrada de posición")
    stop = _positive(position["stop_price"], "Stop de posición")
    if stop >= entry:
        raise ValueError("Posición existente con stop inválido")
    fee = float(position.get("entry_fee", 0.0))
    if not math.isfinite(fee) or fee < 0:
        raise ValueError("Comisión de entrada existente inválida")
    return qty * (entry - stop) + fee + qty * stop * FEE_RATE


def open_positions(state, requests):
    """Abre un lote y reparte el riesgo agregado restante proporcionalmente."""
    if not isinstance(state, dict) or not isinstance(state.get("positions"), dict):
        raise ValueError("Estado de posiciones inválido")
    if not isinstance(requests, list):
        raise ValueError("Las solicitudes deben ser una lista")
    if not requests:
        return []

    initial = _positive(state["initial_balance"], "Capital inicial")
    cash = float(state["cash_usdt"])
    if not math.isfinite(cash) or cash < 0:
        raise ValueError("Saldo inválido")

    normalized, seen = [], set(state["positions"])
    for req in requests:
        if not isinstance(req, dict):
            raise ValueError("Solicitud inválida")
        symbol = req.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip() or symbol in seen:
            raise ValueError("Símbolo inválido o posición ya abierta")
        seen.add(symbol)
        entry = _positive(req.get("entry_price"), "Precio de entrada")
        stop = _positive(req.get("stop_price"), "Stop")
        if stop >= entry:
            raise ValueError("Stop inválido")
        demand = float(req.get("risk_demand_usdt", initial * RISK_PERCENT))
        if not math.isfinite(demand) or demand <= 0:
            raise ValueError("Demanda de riesgo inválida")
        target = req.get("target_price")
        if target is not None:
            target = _positive(target, "Objetivo")
            if target <= entry:
                raise ValueError("Objetivo inválido")
        normalized.append({"symbol": symbol, "entry": entry, "stop": stop,
                           "demand": demand, "per_unit": _risk_per_unit(entry, stop),
                           "target": target})

    existing_risk = sum(_position_risk(p) for p in state["positions"].values())
    risk_cap = initial * RISK_PERCENT
    risk_available = max(0.0, risk_cap - existing_risk)
    if risk_available < 1e-8:
        risk_available = 0.0
    demand_total = sum(r["demand"] for r in normalized)

    exposure_cap = initial * MAX_POSITION_PERCENT
    committed = sum(float(p["quantity"]) * float(p["entry_price"])
                    + float(p.get("entry_fee", 0.0))
                    for p in state["positions"].values())
    exposure_available = max(0.0, exposure_cap - committed)
    if exposure_available < 1e-8:
        exposure_available = 0.0

    # Un factor común conserva el reparto proporcional si efectivo o exposición limitan el lote.
    allocations = [risk_available * req["demand"] / demand_total for req in normalized]
    desired_quantities = [allocation / req["per_unit"]
                          for allocation, req in zip(allocations, normalized)]
    desired_commitment = sum(qty * req["entry"] * (1 + FEE_RATE)
                             for qty, req in zip(desired_quantities, normalized))
    scale = 1.0
    if desired_commitment > 0:
        scale = min(1.0, cash / desired_commitment,
                    exposure_available / desired_commitment)

    planned = []
    for req, allocation, desired_qty in zip(normalized, allocations, desired_quantities):
        quantity = desired_qty * scale
        cost = quantity * req["entry"]
        fee = cost * FEE_RATE
        planned.append((req, allocation, quantity, cost, fee))

    results = []
    for req, allocation, quantity, cost, fee in planned:
        if quantity <= TOLERANCE:
            results.append((False, f"Sin presupuesto disponible para {req['symbol']}"))
            continue
        state["cash_usdt"] = max(0.0, float(state["cash_usdt"]) - cost - fee)
        position = {"entry_price": req["entry"], "stop_price": req["stop"],
                    "quantity": quantity, "entry_fee": fee,
                    "risk_budget": quantity * req["per_unit"],
                    "risk_budget_target": allocation,
                    "opened_at": datetime.now(timezone.utc).isoformat()}
        if req["target"] is not None:
            position["target_price"] = req["target"]
        state["positions"][req["symbol"]] = position
        results.append((True, f"Compra simulada: {req['symbol']} | Riesgo: {position['risk_budget']:.4f} USDT (asignado: {allocation:.4f})"))

    final_risk = sum(_position_risk(p) for p in state["positions"].values())
    final_exposure = sum(float(p["quantity"]) * float(p["entry_price"])
                         + float(p.get("entry_fee", 0.0))
                         for p in state["positions"].values())
    if (final_risk > max(risk_cap, existing_risk) + 1e-8
            or final_exposure > max(exposure_cap, committed) + 1e-8):
        raise AssertionError("Se excedió el límite agregado de riesgo o exposición")
    if any(ok for ok, _ in results):
        save_state(state)
    return results


def open_position(state, symbol, entry_price, stop_price):
    try:
        return open_positions(state, [{"symbol": symbol, "entry_price": entry_price,
                                       "stop_price": stop_price}])[0]
    except (ValueError, KeyError, TypeError) as error:
        return False, str(error)


def close_position(state, symbol, exit_price, reason="manual"):
    position = state["positions"].get(symbol)
    if not position:
        return False, "No existe posición abierta"
    try:
        exit_price = _positive(exit_price, "Precio de salida")
    except ValueError as error:
        return False, str(error)
    quantity = position["quantity"]
    proceeds = quantity * exit_price
    exit_fee = proceeds * FEE_RATE
    state["cash_usdt"] += proceeds - exit_fee
    pnl = proceeds - exit_fee - quantity * position["entry_price"] - position["entry_fee"]
    trade = {**position, "symbol": symbol, "exit_price": exit_price,
             "exit_fee": exit_fee, "net_pnl": pnl, "reason": reason,
             "closed_at": datetime.now(timezone.utc).isoformat()}
    state["history"].append(trade)
    del state["positions"][symbol]
    save_state(state)
    return True, f"Resultado neto: {pnl:.4f} USDT"


def get_status(state):
    invested = sum(p["quantity"] * p["entry_price"] for p in state["positions"].values())
    return {"initial_balance": state["initial_balance"], "cash_usdt": round(state["cash_usdt"], 4),
            "invested_usdt": round(invested, 4), "open_positions": len(state["positions"]),
            "closed_trades": len(state["history"]),
            "realized_pnl": round(sum(t["net_pnl"] for t in state["history"]), 4)}


if __name__ == "__main__":
    print(json.dumps(get_status(load_state()), indent=2))
