"""Read-only performance reporting for the in-memory paper account.

This module performs no network access, file I/O, persistence, or trading.
Prices must be supplied by the caller as BASE/USDT mark prices.
"""
from decimal import Decimal, InvalidOperation

from paper_account import mark_to_market


def _decimal(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def build_performance_report(account, marks):
    """Build a snapshot report without mutating account or marks.

    The report assumes no deposits or withdrawals after account creation.
    Total return is therefore equity minus initial cash. Fees are summed
    from the ledger history and are already reflected in cash/cost basis/PnL.
    """
    if not isinstance(account, dict):
        raise ValueError("account must be a dictionary")
    history = account.get("history")
    if not isinstance(history, list):
        raise ValueError("account.history must be a list")

    initial_cash = _decimal(account.get("initial_cash_usdt"), "initial_cash_usdt")
    if initial_cash <= 0:
        raise ValueError("initial_cash_usdt must be positive")

    valuation = mark_to_market(account, marks)
    fees = Decimal("0")
    buys = 0
    sells = 0
    for index, trade in enumerate(history):
        if not isinstance(trade, dict):
            raise ValueError(f"history[{index}] must be a dictionary")
        fee = _decimal(trade.get("fee_usdt"), f"history[{index}].fee_usdt")
        if fee < 0:
            raise ValueError(f"history[{index}].fee_usdt cannot be negative")
        fees += fee
        side = trade.get("side")
        if side == "BUY":
            buys += 1
        elif side == "SELL":
            sells += 1
        else:
            raise ValueError(f"history[{index}].side must be BUY or SELL")

    cash = _decimal(valuation["cash_usdt"], "cash_usdt")
    market_value = _decimal(valuation["market_value_usdt"], "market_value_usdt")
    equity = _decimal(valuation["equity_usdt"], "equity_usdt")
    realized = _decimal(valuation["realized_pnl_usdt"], "realized_pnl_usdt")
    unrealized = _decimal(valuation["unrealized_pnl_usdt"], "unrealized_pnl_usdt")
    total_pnl = equity - initial_cash
    return_pct = total_pnl / initial_cash * Decimal("100")
    cash_pct = cash / equity * Decimal("100") if equity > 0 else Decimal("0")

    positions = {}
    for asset, position in valuation["positions"].items():
        value = _decimal(position["market_value_usdt"], f"{asset}.market_value_usdt")
        positions[asset] = {
            **position,
            "portfolio_weight_pct": str(value / equity * Decimal("100")) if equity > 0 else "0",
        }

    return {
        "quote_currency": "USDT",
        "initial_cash_usdt": str(initial_cash),
        "cash_usdt": str(cash),
        "market_value_usdt": str(market_value),
        "equity_usdt": str(equity),
        "total_pnl_usdt": str(total_pnl),
        "total_return_pct": str(return_pct),
        "realized_pnl_usdt": str(realized),
        "unrealized_pnl_usdt": str(unrealized),
        "fees_paid_usdt": str(fees),
        "cash_weight_pct": str(cash_pct),
        "trade_count": len(history),
        "buy_count": buys,
        "sell_count": sells,
        "open_position_count": len(positions),
        "positions": positions,
    }
