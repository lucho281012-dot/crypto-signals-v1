"""Read-only reporting adapter for the legacy paper_trading state.

Pure translation only: no file I/O, network access, state mutation, or trades.
Callers provide current USDT mark prices for every open position. Mark keys
may be BASE, BASE/USDT, or BASEUSDT; report keys are normalized to BASE.
"""
import re
from decimal import Decimal, InvalidOperation


def _decimal(value, field):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _positive(value, field):
    number = _decimal(value, field)
    if number <= 0:
        raise ValueError(f"{field} must be positive")
    return number


def _non_negative(value, field):
    number = _decimal(value, field)
    if number < 0:
        raise ValueError(f"{field} cannot be negative")
    return number


def _asset_from_symbol(symbol):
    if not isinstance(symbol, str):
        raise ValueError(f"unsupported symbol: {symbol!r}; expected BASE/USDT")
    match = re.fullmatch(r"([A-Z0-9]+)(?:/)?USDT", symbol)
    if not match:
        raise ValueError(f"unsupported symbol: {symbol!r}; expected BASE/USDT")
    return match.group(1)


def _mark_for_asset(marks, asset, symbol):
    """Resolve common mark-key styles and reject conflicting duplicate values."""
    keys = (asset, symbol, asset + "USDT")
    found = []
    for key in keys:
        if key in marks:
            value = _positive(marks[key], f"marks[{key}]")
            if value not in found:
                found.append(value)
    if not found:
        raise ValueError(f"missing mark price for {asset}; expected one of {keys}")
    if len(found) > 1:
        raise ValueError(f"conflicting mark prices supplied for {asset}")
    return found[0]


def build_legacy_paper_report(state, marks):
    """Translate paper_trading state into a canonical dashboard report.

    Equity is cash plus marked market value. Closed-trade net_pnl is already
    net of fees and is not adjusted again. The fee total is informational:
    closed entry/exit fees plus entry fees on currently open positions.
    """
    if not isinstance(state, dict):
        raise ValueError("state must be a dictionary")
    if not isinstance(marks, dict):
        raise ValueError("marks must be a dictionary")

    initial = _positive(state.get("initial_balance"), "initial_balance")
    cash = _non_negative(state.get("cash_usdt"), "cash_usdt")
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
        if asset in report_positions:
            raise ValueError(f"duplicate position for normalized asset: {asset}")
        if not isinstance(position, dict):
            raise ValueError(f"positions[{symbol}] must be a dictionary")

        quantity = _positive(position.get("quantity"), f"{symbol}.quantity")
        entry = _positive(position.get("entry_price"), f"{symbol}.entry_price")
        # Fees are required: silently defaulting missing fees to zero can
        # understate costs and make the financial report misleading.
        entry_fee = _non_negative(position.get("entry_fee"), f"{symbol}.entry_fee")
        mark = _mark_for_asset(marks, asset, symbol)

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
            "mark_price_usdt": str(mark),
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
        "trade_count": len(history),
        # A history item is a completed buy/sell round trip. Each open
        # position contributes one additional buy and no sell yet.
        "buy_count": len(history) + len(report_positions),
        "sell_count": len(history),
        "open_position_count": len(report_positions),
        "positions": report_positions,
    }
