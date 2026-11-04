
RISK_PERCENT = 0.01
MAX_POSITION_PERCENT = 0.95


def calculate_position(balance, entry_price, stop_price):
    if balance <= 0:
        raise ValueError("El saldo debe ser positivo")

    if entry_price <= 0 or stop_price <= 0:
        raise ValueError("Los precios deben ser positivos")

    if stop_price >= entry_price:
        raise ValueError("En Spot, el stop debe estar debajo de la entrada")

    risk_amount = balance * RISK_PERCENT

    risk_per_unit = entry_price - stop_price

    quantity_by_risk = risk_amount / risk_per_unit

    max_investment = balance * MAX_POSITION_PERCENT

    quantity_by_balance = max_investment / entry_price

    quantity = min(quantity_by_risk, quantity_by_balance)

    investment = quantity * entry_price

    return {
        "risk_usdt": round(risk_amount, 4),
        "quantity": round(quantity, 8),
        "investment_usdt": round(investment, 4),
        "entry_price": entry_price,
        "stop_price": stop_price
    }
