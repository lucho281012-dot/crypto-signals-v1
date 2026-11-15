"""Read-only reporting adapter for the legacy paper_trading state.

Pure translation only: no file I/O, network access, state mutation, or trades.
Callers provide current mark prices for every open BASE/USDT position.
"""
from decimal import Decimal, InvalidOperation


def _decimal(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _non_negative(value, field):
    number = _decimal(value, field)
    if number < 0:
        raise ValueError(f"{field} cannot be negative")
    return number


def _asset_from_symbol(symbol):
    if not isinstance(symbol, str) or not symbol.endswith("/USDT"):
        raise ValueError(f"unsupported symbol: {symbol!r}; expected BASE/USDT")
    asset = symbol[:-5]
    if not asset or "/" in asset:
        raise ValueError(f"invalid BASE/USDT symbol: {symbol!r}")
    return asset


def build_legacy_paper_report(state, marks):
    """Translate paper_trading.load_state() data into a dashboard report.

    marks maps full symbols (for example BTC/USDT) to positive prices.
    Equity is cash plus marked market value. Open-position cost basis includes
    its entry fee; realized P&L comes from closed trades' net_pnl. Fees are
    reported for transparency and are not subtracted a second time.
    """
    if not isinstance(state, dict):
        raise ValueError("state must be a dictionary")
    if not isinstance(marks, dict):
        raise ValueError("marks must be a dictionary")

    initial = _decimal(state.get("initial_balance"), "initial_balance")
    cash = _decimal(state.get("cash_usdt"), "cash_usdt")
    if initial <= 0:
        raise ValueError("initial_balance must be positive")
    if cash < 0:
        raise ValueError("cash_usdt cannot be negative")

    positions = state.get("positions")
    history = state.get("history")
    if not isinstance(positions, dict):
        raise ValueError("positions must be a dictionary")
    if not isinstance(history, list):
        raise ValueError("history must be a list")

    report_positions = {}
    market_value = Decimal("0")
    open_entry_fees = Decimal("0")

    for symbol, position in sorted(positions.items()):
        asset = _asset_from_symbol(symbol)
        if not isinstance(position, dict):
            raise ValueError(f"positions[{symbol}] must be a dictionary")
        quantity = _non_negative(position.get("quantity"), f"{symbol}.quantity")
        entry = _decimal(position.get("entry_price"), f"{symbol}.entry_price")
        entry_fee = _non_negative(position.get("entry_fee"), f"{symbol}.entry_fee")
        mark = _decimal(marks.get(symbol), f"marks[{symbol}]")
        if quantity <= 0 or entry <= 0 or mark <= 0:
            raise ValueError(f"{symbol} quantity and prices must be positive")

        value = quantity * mark
        cost_basis = quantity * entry + entry_fee
        unrealized = value - cost_basis
        market_value += value
        open_entry_fees += entry_fee
        report_positions[asset] = {
            "symbol": symbol,
            "quantity": str(quantity),
            "entry_price": str(entry),
            "mark_price": str(mark),
            "cost_basis_usdt": str(cost_basis),
            "market_value_usdt": str(value),
            "unrealized_pnl_usdt": str(unrealized),
            "portfolio_weight_pct": "0",
        }

    realized = Decimal("0")
    closed_entry_fees = Decimal("0")
    exit_fees = Decimal("0")
    for index, trade in enumerate(history):
        if not isinstance(trade, dict):
            raise ValueError(f"history[{index}] must be a dictionary")
        realized += _decimal(trade.get("net_pnl"), f"history[{index}].net_pnl")
        closed_entry_fees += _non_negative(
            trade.get("entry_fee"), f"history[{index}].entry_fee"
        )
        exit_fees += _non_negative(
            trade.get("exit_fee"), f"history[{index}].exit_fee"
        )

    equity = cash + market_value
    total_pnl = equity - initial
    unrealized_total = sum(
        (Decimal(item["unrealized_pnl_usdt"]) for item in report_positions.values()),
        Decimal("0"),
    )
    fees = closed_entry_fees + exit_fees + open_entry_fees

    for item in report_positions.values():
        value = Decimal(item["market_value_usdt"])
        item["portfolio_weight_pct"] = (
            str(value / equity * Decimal("100")) if equity > 0 else "0"
        )

    return {
        "quote_currency": "USDT",
        "initial_cash_usdt": str(initial),
        "cash_usdt": str(cash),
        "market_value_usdt": str(market_value),
        "equity_usdt": str(equity),
        "total_pnl_usdt": str(total_pnl),
        "total_return_pct": str(total_pnl / initial * Decimal("100")),
        "realized_pnl_usdt": str(realized),
        "unrealized_pnl_usdt": str(unrealized_total),
        "fees_paid_usdt": str(fees),
        "cash_weight_pct": str(cash / equity * Decimal("100")) if equity > 0 else "0",
        "trade_count": len(history) * 2 + len(report_positions),
        "buy_count": len(history) + len(report_positions),
        "sell_count": len(history),
        "open_position_count": len(report_positions),
        "positions": report_positions,
    }
