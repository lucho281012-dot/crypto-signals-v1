import json
import math
from pathlib import Path
from datetime import datetime, timezone

INITIAL_BALANCE = 100.0
RISK_PERCENT = 0.01
MAX_POSITION_PERCENT = 0.95
FEE_RATE = 0.001
SLIPPAGE_BPS = 5.0
MIN_NOTIONAL_USDT = 5.0

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
        file.flush()

    temp_file.replace(STATE_FILE)


def risk_per_unit(entry_price, stop_price, fee_rate=FEE_RATE,
                  slippage_bps=SLIPPAGE_BPS):
    entry = float(entry_price)
    stop = float(stop_price)
    exit_fill = stop * (1.0 - float(slippage_bps) / 10000.0)
    if entry <= 0 or stop <= 0 or stop >= entry or exit_fill <= 0:
        raise ValueError("Invalid entry/stop prices for risk calculation")
    return (
        entry - exit_fill
        + entry * float(fee_rate)
        + exit_fill * float(fee_rate)
    )


def calculate_open_risk(state):
    total = 0.0
    for symbol, position in state.get("positions", {}).items():
        try:
            quantity = float(position["quantity"])
            entry = float(position["entry_price"])
            stop = float(position["stop_price"])
            if quantity <= 0:
                raise ValueError("non-positive quantity")
            total += quantity * risk_per_unit(entry, stop)
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"Cannot validate existing open risk for {symbol}: {error}"
            ) from error
    return total


def open_positions_batch(state, candidates, min_notional=MIN_NOTIONAL_USDT):
    """Open simultaneous candidates under one shared portfolio risk budget.

    Candidates are dictionaries with symbol, entry_price, stop_price and
    optional target_price/metadata. One common scaling factor is applied
    across the batch. Existing positions are re-priced from their actual
    quantity, entry and stop; stored risk_budget is never trusted.
    """
    positions = state.setdefault("positions", {})
    if not candidates:
        return {}

    if not isinstance(candidates, (list, tuple)):
        raise TypeError("candidates must be a list or tuple")

    seen = set()
    normalized = []
    for item in candidates:
        symbol = str(item["symbol"])
        if symbol in seen or symbol in positions:
            continue
        seen.add(symbol)
        entry = float(item["entry_price"])
        stop = float(item["stop_price"])
        unit_risk = risk_per_unit(entry, stop)
        normalized.append((item, symbol, entry, stop, unit_risk))

    if not normalized:
        return {}

    initial = float(state["initial_balance"])
    cash = float(state["cash_usdt"])
    if initial <= 0 or cash <= 0:
        return {symbol: (False, "Saldo insuficiente") for _, symbol, *_ in normalized}

    try:
        current_risk = calculate_open_risk(state)
    except RuntimeError:
        # Fail closed: never add exposure when existing risk cannot be verified.
        return {
            symbol: (False, "Riesgo de posiciones existentes no verificable")
            for _, symbol, *_ in normalized
        }

    current_exposure = sum(
        float(p["quantity"]) * float(p["entry_price"])
        for p in positions.values()
    )
    risk_remaining = max(0.0, initial * RISK_PERCENT - current_risk)
    exposure_remaining = max(
        0.0, initial * MAX_POSITION_PERCENT - current_exposure
    )

    if risk_remaining <= 0 or exposure_remaining <= 0:
        return {
            symbol: (False, "Presupuesto agregado de riesgo o exposición agotado")
            for _, symbol, *_ in normalized
        }

    # Each candidate's unscaled size targets the full portfolio risk cap.
    # A single factor then shares the remaining budget proportionally.
    base = []
    total_base_risk = 0.0
    total_base_exposure = 0.0
    total_base_cash = 0.0
    for item, symbol, entry, stop, unit_risk in normalized:
        target_quantity = initial * RISK_PERCENT / unit_risk
        notional = target_quantity * entry
        cash_cost = notional * (1.0 + FEE_RATE)
        base.append((item, symbol, entry, stop, unit_risk, target_quantity))
        total_base_risk += target_quantity * unit_risk
        total_base_exposure += notional
        total_base_cash += cash_cost

    factor = min(
        1.0,
        risk_remaining / total_base_risk if total_base_risk else 0.0,
        exposure_remaining / total_base_exposure if total_base_exposure else 0.0,
        cash / total_base_cash if total_base_cash else 0.0,
    )

    results = {}
    pending = []
    for item, symbol, entry, stop, unit_risk, target_quantity in base:
        quantity = target_quantity * factor
        notional = quantity * entry
        if not math.isfinite(quantity) or quantity <= 0 or notional < float(min_notional):
            results[symbol] = (False, f"Notional inferior al mínimo de {float(min_notional):.2f} USDT")
            continue
        pending.append((item, symbol, entry, stop, unit_risk, quantity, notional))

    # No partial batch is committed if any rounding/validation issue appears.
    total_cost = sum(n * (1.0 + FEE_RATE) for *_, n in pending)
    total_risk = sum(q * unit for _, _, _, _, unit, q, _ in pending)
    total_exposure = sum(n for *_, n in pending)
    if (
        total_cost > cash + 1e-9
        or current_exposure + total_exposure > initial * MAX_POSITION_PERCENT + 1e-9
        or current_risk + total_risk > initial * RISK_PERCENT + 1e-9
    ):
        return {
            symbol: (False, "La validación final del presupuesto compartido falló")
            for _, symbol, *_ in normalized
        }

    if pending:
        now = datetime.now(timezone.utc).isoformat()
        new_positions = {}
        for item, symbol, entry, stop, unit, quantity, notional in pending:
            entry_fee = notional * FEE_RATE
            actual_risk = quantity * unit
            position = {
                "entry_price": entry,
                "stop_price": stop,
                "quantity": quantity,
                "entry_fee": entry_fee,
                "risk_budget": actual_risk,
                "risk_budget_target": initial * RISK_PERCENT,
                "opened_at": now,
                "entry_model": "post_signal_reference_quote",
            }
            if item.get("target_price") is not None:
                position["target_price"] = float(item["target_price"])
            for key in (
                "signal_candle_timestamp", "signal_confirmed_at",
                "entry_decision_at", "quote_timestamp", "quote_price",
                "entry_delay_seconds", "strategy_version", "signal_snapshot"
            ):
                if key in item:
                    position[key] = item[key]
            new_positions[symbol] = position

        # Mutate the in-memory state only after all candidates validate.
        positions.update(new_positions)
        state["cash_usdt"] = max(0.0, cash - total_cost)
        save_state(state)
        for symbol, position in new_positions.items():
            results[symbol] = (
                True,
                f"Compra simulada: {symbol} | Riesgo agregado asignado: "
                f"{position['risk_budget']:.4f} USDT"
            )

    return results


def open_position(state, symbol, entry_price, stop_price):
    result = open_positions_batch(state, [{
        "symbol": symbol,
        "entry_price": entry_price,
        "stop_price": stop_price,
    }])
    return result.get(symbol, (False, "Entrada rechazada"))


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
        - float(position["entry_fee"])
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
