"""Pure in-memory paper account ledger; no exchange or persistence access.

All monetary and quantity values are stored as decimal strings to avoid
introducing binary-float drift into the account ledger.
"""
from decimal import Decimal, InvalidOperation


def _d(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _positive(value, field):
    result = _d(value, field)
    if result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


def _symbol_base(symbol):
    if not isinstance(symbol, str) or "/" not in symbol:
        raise ValueError("symbol must use BASE/QUOTE format")
    base, quote = symbol.split("/", 1)
    if not base or quote != "USDT":
        raise ValueError("only BASE/USDT symbols are supported")
    return base


def create_account(initial_cash_usdt):
    """Create a fresh account without touching any file or external state."""
    cash = _positive(initial_cash_usdt, "initial_cash_usdt")
    return {
        "quote_currency": "USDT",
        "initial_cash_usdt": str(cash),
        "cash_usdt": str(cash),
        "positions": {},
        "realized_pnl_usdt": "0",
        "history": [],
    }


def apply_execution(account, execution):
    """Return a new account after one complete validated paper execution.

    BUY adds fee-inclusive cost basis. SELL removes average-cost basis and
    realizes net proceeds less allocated basis. The input account is untouched.
    """
    if not isinstance(account, dict) or not isinstance(execution, dict):
        raise ValueError("account and execution must be dictionaries")
    if execution.get("ok") is not True:
        raise ValueError("execution is not successful")
    side = execution.get("side")
    if side not in ("BUY", "SELL"):
        raise ValueError("execution side must be BUY or SELL")

    base = _symbol_base(execution.get("symbol"))
    qty = _positive(execution.get("filled_quantity"), "filled_quantity")
    price = _positive(execution.get("average_fill_price"), "average_fill_price")
    notional = _positive(execution.get("gross_notional_usdt"), "gross_notional_usdt")
    fee = _d(execution.get("fee_usdt"), "fee_usdt")
    cash_flow = _d(execution.get("cash_flow_usdt"), "cash_flow_usdt")
    if fee < 0:
        raise ValueError("fee_usdt cannot be negative")
    if abs(notional - qty * price) > Decimal("0.00000001"):
        raise ValueError("execution notional does not match quantity and average price")

    expected_flow = -(notional + fee) if side == "BUY" else notional - fee
    if abs(cash_flow - expected_flow) > Decimal("0.00000001"):
        raise ValueError("execution cash flow is inconsistent with notional and fee")

    cash = _d(account.get("cash_usdt"), "account.cash_usdt")
    positions = account.get("positions")
    if not isinstance(positions, dict):
        raise ValueError("account.positions must be a dictionary")
    old_position = positions.get(base, {"quantity": "0", "cost_basis_usdt": "0"})
    old_qty = _d(old_position.get("quantity"), "position.quantity")
    old_basis = _d(old_position.get("cost_basis_usdt"), "position.cost_basis_usdt")
    if old_qty < 0 or old_basis < 0:
        raise ValueError("existing position values cannot be negative")

    new_positions = {key: dict(value) for key, value in positions.items()}
    realized = _d(account.get("realized_pnl_usdt", "0"), "realized_pnl_usdt")
    trade_record = {
        "symbol": execution["symbol"],
        "side": side,
        "quantity": str(qty),
        "average_fill_price": str(price),
        "gross_notional_usdt": str(notional),
        "fee_usdt": str(fee),
        "cash_flow_usdt": str(cash_flow),
    }

    if side == "BUY":
        if cash + cash_flow < 0:
            raise ValueError("insufficient paper cash for BUY including fees")
        new_qty = old_qty + qty
        new_basis = old_basis + notional + fee
        new_positions[base] = {
            "quantity": str(new_qty),
            "cost_basis_usdt": str(new_basis),
            "average_cost_usdt": str(new_basis / new_qty),
        }
    else:
        if qty > old_qty:
            raise ValueError("insufficient position quantity for SELL")
        if old_qty <= 0:
            raise ValueError("cannot SELL an empty position")
        allocated_basis = old_basis * qty / old_qty
        realized_trade = cash_flow - allocated_basis
        realized += realized_trade
        new_qty = old_qty - qty
        new_basis = old_basis - allocated_basis
        if new_qty == 0:
            new_positions.pop(base, None)
        else:
            new_positions[base] = {
                "quantity": str(new_qty),
                "cost_basis_usdt": str(new_basis),
                "average_cost_usdt": str(new_basis / new_qty),
            }
        trade_record["allocated_cost_basis_usdt"] = str(allocated_basis)
        trade_record["realized_pnl_usdt"] = str(realized_trade)

    new_cash = cash + cash_flow
    new_history = list(account.get("history", [])) + [trade_record]
    return {
        "quote_currency": "USDT",
        "initial_cash_usdt": str(_positive(account.get("initial_cash_usdt"), "initial_cash_usdt")),
        "cash_usdt": str(new_cash),
        "positions": new_positions,
        "realized_pnl_usdt": str(realized),
        "history": new_history,
    }


def mark_to_market(account, marks):
    """Calculate equity and unrealized PnL from supplied BASE/USDT marks."""
    if not isinstance(account, dict) or not isinstance(marks, dict):
        raise ValueError("account and marks must be dictionaries")
    cash = _d(account.get("cash_usdt"), "account.cash_usdt")
    market_value = Decimal("0")
    unrealized = Decimal("0")
    details = {}
    for base, position in account.get("positions", {}).items():
        if base not in marks:
            raise ValueError(f"missing mark price for {base}")
        mark = _positive(marks[base], f"mark price for {base}")
        qty = _positive(position.get("quantity"), f"{base}.quantity")
        basis = _positive(position.get("cost_basis_usdt"), f"{base}.cost_basis_usdt")
        value = qty * mark
        pnl = value - basis
        market_value += value
        unrealized += pnl
        details[base] = {
            "quantity": str(qty),
            "mark_price_usdt": str(mark),
            "market_value_usdt": str(value),
            "cost_basis_usdt": str(basis),
            "unrealized_pnl_usdt": str(pnl),
        }
    return {
        "cash_usdt": str(cash),
        "market_value_usdt": str(market_value),
        "equity_usdt": str(cash + market_value),
        "realized_pnl_usdt": str(_d(account.get("realized_pnl_usdt", "0"), "realized_pnl_usdt")),
        "unrealized_pnl_usdt": str(unrealized),
        "positions": details,
    }
