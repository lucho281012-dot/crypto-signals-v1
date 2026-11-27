
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
        state.setdefault("last_processed_close", {})
        return state

    return {
        "initial_balance": INITIAL_BALANCE,
        "cash_usdt": INITIAL_BALANCE,
        "positions": {},
        "history": [],
        "last_processed_candle": {},
        "last_processed_close": {}
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
    actual_stop_risk = quantity * risk_per_unit_with_fees

    if quantity <= 0 or cost + entry_fee > balance + 1e-10:
        return False, "Saldo insuficiente"

    # Avoid a tiny negative balance caused only by floating-point rounding
    # when quantity is capped exactly to available cash.
    state["cash_usdt"] = max(0.0, balance - cost - entry_fee)

    state["positions"][symbol] = {
        "entry_price": entry_price,
        "stop_price": stop_price,
        "quantity": quantity,
        "entry_fee": entry_fee,
        # risk_budget is the estimated loss at the stop, including fees.
        # Keep the target separately so balance caps cannot overstate risk.
        "risk_budget": actual_stop_risk,
        "risk_budget_target": risk_amount,
        "opened_at": datetime.now(timezone.utc).isoformat()
    }

    save_state(state)

    return True, (
        f"Compra simulada: {symbol} | "
        f"Riesgo estimado al stop: {actual_stop_risk:.4f} USDT "
        f"(objetivo: {risk_amount:.4f} USDT)"
    )


def close_position(state, symbol, exit_price, reason="manual"):
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

    save_state(state)

    return True, f"Resultado neto: {pnl:.4f} USDT"



SLIPPAGE_BPS = 5.0
QUANTITY_DECIMALS = 8


def _finite_positive(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Estado inválido: {field} no es numérico.")
    if not __import__("math").isfinite(number) or number <= 0:
        raise ValueError(f"Estado inválido: {field} debe ser finito y positivo.")
    return number


def _position_stop_risk(position, fee_rate, slippage_bps):
    """Recalcula riesgo abierto; no confía en risk_budget persistido."""
    quantity = _finite_positive(position.get("quantity"), "quantity")
    entry = _finite_positive(position.get("entry_price"), "entry_price")
    stop = _finite_positive(position.get("stop_price"), "stop_price")
    if stop >= entry:
        raise ValueError("Estado inválido: stop_price debe ser menor que entry_price.")

    if "entry_fee" not in position:
        raise ValueError("Estado inválido: posición abierta sin entry_fee.")
    try:
        entry_fee = float(position["entry_fee"])
    except (TypeError, ValueError):
        raise ValueError("Estado inválido: entry_fee no es numérico.")
    if not __import__("math").isfinite(entry_fee) or entry_fee < 0:
        raise ValueError("Estado inválido: entry_fee debe ser finito y no negativo.")

    exit_fill = stop * (1 - slippage_bps / 10000)
    if exit_fill <= 0:
        raise ValueError("Estado inválido: precio estimado de salida no positivo.")
    return (
        quantity * (entry - exit_fill)
        + entry_fee
        + quantity * exit_fill * fee_rate
    )


def allocate_batch(
    state,
    signals,
    risk_limit=RISK_PERCENT,
    exposure_limit=MAX_POSITION_PERCENT,
    fee_rate=FEE_RATE,
    slippage_bps=SLIPPAGE_BPS,
):
    """Asigna un presupuesto compartido a señales simultáneas sin mutar state.

    Cada señal válida debe incluir symbol, entry_price, stop_price y
    requested_risk. Las señales inválidas se rechazan individualmente.
    Un estado de posiciones abiertas incompleto/inconsistente bloquea el lote.
    """
    import math

    initial_balance = _finite_positive(
        state.get("initial_balance"), "initial_balance"
    )
    cash = state.get("cash_usdt")
    try:
        cash = float(cash)
    except (TypeError, ValueError):
        raise ValueError("Estado inválido: cash_usdt no es numérico.")
    if not math.isfinite(cash) or cash < 0:
        raise ValueError("Estado inválido: cash_usdt debe ser finito y no negativo.")

    for name, value in (
        ("risk_limit", risk_limit),
        ("exposure_limit", exposure_limit),
        ("fee_rate", fee_rate),
        ("slippage_bps", slippage_bps),
    ):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} no es numérico.")
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{name} debe ser finito y no negativo.")
    risk_limit = float(risk_limit)
    exposure_limit = float(exposure_limit)
    fee_rate = float(fee_rate)
    slippage_bps = float(slippage_bps)
    if risk_limit > 1 or exposure_limit > 1 or fee_rate >= 1 or slippage_bps >= 10000:
        raise ValueError("Límite o tasa fuera de rango.")

    positions = state.get("positions")
    if not isinstance(positions, dict):
        raise ValueError("Estado inválido: positions debe ser un diccionario.")

    open_risk = 0.0
    open_exposure = 0.0
    for symbol, position in positions.items():
        if not isinstance(position, dict):
            raise ValueError(f"Estado inválido: posición de {symbol} no es un objeto.")
        open_risk += _position_stop_risk(position, fee_rate, slippage_bps)
        quantity = _finite_positive(position.get("quantity"), "quantity")
        entry = _finite_positive(position.get("entry_price"), "entry_price")
        open_exposure += quantity * entry

    risk_cap = initial_balance * risk_limit
    exposure_cap = initial_balance * exposure_limit
    risk_available = max(0.0, risk_cap - open_risk)
    exposure_available = max(0.0, exposure_cap - open_exposure)

    rejected = {}
    eligible = {}
    seen = set()
    for signal in signals:
        symbol = signal.get("symbol") if isinstance(signal, dict) else None
        if not isinstance(symbol, str) or not symbol.strip():
            rejected[f"invalid_signal_{len(rejected) + 1}"] = "símbolo inválido"
            continue
        if symbol in seen:
            rejected[symbol] = "símbolo duplicado en el lote"
            continue
        seen.add(symbol)
        if symbol in positions:
            rejected[symbol] = "ya existe una posición abierta"
            continue
        try:
            entry = _finite_positive(signal.get("entry_price"), "entry_price")
            stop = _finite_positive(signal.get("stop_price"), "stop_price")
            demand = _finite_positive(signal.get("requested_risk"), "requested_risk")
            if stop >= entry:
                raise ValueError("stop_price debe ser menor que entry_price")
            exit_fill = stop * (1 - slippage_bps / 10000)
            risk_per_unit = (
                entry - exit_fill
                + entry * fee_rate
                + exit_fill * fee_rate
            )
            if not math.isfinite(risk_per_unit) or risk_per_unit <= 0:
                raise ValueError("riesgo por unidad no positivo")
            eligible[symbol] = {
                "entry_price": entry,
                "stop_price": stop,
                "requested_risk": demand,
                "risk_per_unit": risk_per_unit,
            }
        except (ValueError, TypeError) as error:
            rejected[symbol] = str(error)

    demand_total = sum(item["requested_risk"] for item in eligible.values())
    if not eligible or demand_total <= 0 or risk_available <= 0 or exposure_available <= 0 or cash <= 0:
        return {
            "allocations": {},
            "rejected": rejected,
            "totals": {
                "open_risk": open_risk,
                "risk_available": risk_available,
                "open_exposure": open_exposure,
                "exposure_available": exposure_available,
                "risk": 0.0,
                "exposure": 0.0,
                "cash_required": 0.0,
            },
        }

    # Primero se comparte el riesgo proporcionalmente; nunca se amplía una
    # demanda menor para consumir el presupuesto sobrante.
    risk_factor = min(1.0, risk_available / demand_total)
    provisional = {}
    for symbol in sorted(eligible):
        item = eligible[symbol]
        risk_amount = item["requested_risk"] * risk_factor
        quantity = risk_amount / item["risk_per_unit"]
        provisional[symbol] = {
            **item,
            "quantity": quantity,
        }

    provisional_exposure = sum(
        item["quantity"] * item["entry_price"]
        for item in provisional.values()
    )
    provisional_cash = sum(
        item["quantity"] * item["entry_price"] * (1 + fee_rate)
        for item in provisional.values()
    )
    exposure_factor = (
        min(1.0, exposure_available / provisional_exposure)
        if provisional_exposure > 0 else 0.0
    )
    cash_factor = (
        min(1.0, cash / provisional_cash)
        if provisional_cash > 0 else 0.0
    )
    common_factor = min(1.0, exposure_factor, cash_factor)

    allocations = {}
    for symbol, item in provisional.items():
        quantity = math.floor(
            item["quantity"] * common_factor * (10 ** QUANTITY_DECIMALS)
        ) / (10 ** QUANTITY_DECIMALS)
        if quantity <= 0:
            rejected[symbol] = "cantidad inferior a la precisión permitida"
            continue
        notional = quantity * item["entry_price"]
        entry_fee = notional * fee_rate
        actual_risk = quantity * item["risk_per_unit"]
        allocations[symbol] = {
            "quantity": quantity,
            "entry_price": item["entry_price"],
            "stop_price": item["stop_price"],
            "risk": actual_risk,
            "exposure": notional,
            "entry_fee": entry_fee,
            "cash_required": notional + entry_fee,
            "requested_risk": item["requested_risk"],
        }

    total_risk = sum(item["risk"] for item in allocations.values())
    total_exposure = sum(item["exposure"] for item in allocations.values())
    total_cash = sum(item["cash_required"] for item in allocations.values())

    # Revalidación estricta tras el redondeo hacia abajo.
    tolerance = 1e-9
    if (
        open_risk + total_risk > risk_cap + tolerance
        or open_exposure + total_exposure > exposure_cap + tolerance
        or total_cash > cash + tolerance
    ):
        raise ArithmeticError("La asignación redondeada excede un límite.")

    return {
        "allocations": allocations,
        "rejected": rejected,
        "totals": {
            "open_risk": open_risk,
            "risk_available": risk_available,
            "open_exposure": open_exposure,
            "exposure_available": exposure_available,
            "risk": total_risk,
            "exposure": total_exposure,
            "cash_required": total_cash,
        },
    }


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


