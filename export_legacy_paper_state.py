"""Read-only adapter from legacy paper_state.json to dashboard history JSON.

This module only reads the simulator state and a separate marks JSON file.
It never imports paper_trading, calls the bot, writes files, or contacts an exchange.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

from paper_report_history import (
    append_report_snapshot,
    build_report_snapshot,
    deserialize_report_history,
    serialize_report_history,
)


def _decimal(value, field, *, positive=False, non_negative=False):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{field} must be positive")
    if non_negative and result < 0:
        raise ValueError(f"{field} cannot be negative")
    return result


def _base_asset(symbol):
    """Normalize BASE/USDT and compact BASEUSDT symbols to BASE."""
    if not isinstance(symbol, str):
        raise ValueError(f"unsupported paper symbol: {symbol!r}")
    match = re.fullmatch(r"([A-Z0-9]+)(?:/)?USDT", symbol)
    if not match:
        raise ValueError(f"unsupported paper symbol: {symbol!r}")
    return match.group(1)


def _mark_for_asset(marks, base, symbol):
    keys = (base, symbol, base + "USDT")
    values = []
    for key in keys:
        if key in marks:
            value = _decimal(marks[key], f"marks.{key}", positive=True)
            if value not in values:
                values.append(value)
    if not values:
        raise ValueError(f"missing mark price for {base}; accepted keys: {keys}")
    if len(values) > 1:
        raise ValueError(f"conflicting mark prices supplied for {base}")
    return values[0]


def build_legacy_state_report(state, marks):
    """Convert an immutable legacy state snapshot to canonical dashboard metrics."""
    if not isinstance(state, dict) or not isinstance(marks, dict):
        raise ValueError("state and marks must be JSON objects")
    initial = _decimal(state.get("initial_balance"), "initial_balance", positive=True)
    cash = _decimal(state.get("cash_usdt"), "cash_usdt", non_negative=True)
    positions = state.get("positions")
    history = state.get("history")
    if not isinstance(positions, dict) or not isinstance(history, list):
        raise ValueError("state must contain positions object and history list")

    report_positions = {}
    market_value = Decimal("0")
    open_entry_fees = Decimal("0")
    for symbol, position in sorted(positions.items()):
        base = _base_asset(symbol)
        if base in report_positions:
            raise ValueError(f"duplicate position for normalized asset: {base}")
        if not isinstance(position, dict):
            raise ValueError(f"position {symbol} must be an object")
        quantity = _decimal(position.get("quantity"), f"{symbol}.quantity", positive=True)
        entry = _decimal(position.get("entry_price"), f"{symbol}.entry_price", positive=True)
        entry_fee = _decimal(position.get("entry_fee"), f"{symbol}.entry_fee", non_negative=True)
        mark = _mark_for_asset(marks, base, symbol)
        value = quantity * mark
        cost_basis = quantity * entry + entry_fee
        unrealized = value - cost_basis
        market_value += value
        open_entry_fees += entry_fee
        report_positions[base] = {
            "symbol": symbol,
            "quantity": str(quantity),
            "entry_price": str(entry),
            "mark_price": str(mark),
            "mark_price_usdt": str(mark),
            "market_value_usdt": str(value),
            "cost_basis_usdt": str(cost_basis),
            "unrealized_pnl_usdt": str(unrealized),
            "portfolio_weight_pct": "0",
        }

    realized = Decimal("0")
    closed_entry_fees = Decimal("0")
    exit_fees = Decimal("0")
    for index, trade in enumerate(history):
        if not isinstance(trade, dict):
            raise ValueError(f"history[{index}] must be an object")
        realized += _decimal(trade.get("net_pnl"), f"history[{index}].net_pnl")
        closed_entry_fees += _decimal(
            trade.get("entry_fee"), f"history[{index}].entry_fee", non_negative=True
        )
        exit_fees += _decimal(
            trade.get("exit_fee"), f"history[{index}].exit_fee", non_negative=True
        )

    equity = cash + market_value
    pnl = equity - initial
    for item in report_positions.values():
        value = Decimal(item["market_value_usdt"])
        item["portfolio_weight_pct"] = str(
            value / equity * Decimal("100")
        ) if equity > 0 else "0"

    return {
        "quote_currency": "USDT",
        "initial_cash_usdt": str(initial),
        "equity_usdt": str(equity),
        "cash_usdt": str(cash),
        "market_value_usdt": str(market_value),
        "total_pnl_usdt": str(pnl),
        "total_return_pct": str(pnl / initial * Decimal("100")),
        "realized_pnl_usdt": str(realized),
        "unrealized_pnl_usdt": str(sum(
            (Decimal(item["unrealized_pnl_usdt"]) for item in report_positions.values()),
            Decimal("0"),
        )),
        "fees_paid_usdt": str(closed_entry_fees + exit_fees + open_entry_fees),
        "cash_weight_pct": str(cash / equity * Decimal("100")) if equity > 0 else "0",
        "trade_count": len(history),
        "buy_count": len(history) + len(report_positions),
        "sell_count": len(history),
        "open_position_count": len(report_positions),
        "positions": report_positions,
    }


def export_state_json(
    state_path, marks_path=None, captured_at=None, snapshot_id=None, history_path=None
):
    source = Path(state_path)
    if source.name != "paper_state.json":
        raise ValueError("input must be the dedicated paper_state.json file")
    state = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("paper state must contain a JSON object")

    marks = {}
    if marks_path is not None:
        marks_data = json.loads(Path(marks_path).read_text(encoding="utf-8"))
        if not isinstance(marks_data, dict):
            raise ValueError("marks file must contain a JSON object")
        marks = marks_data

    report = build_legacy_state_report(state, marks)
    now = datetime.now(timezone.utc)
    timestamp = captured_at or now.isoformat()
    identifier = snapshot_id or "legacy-" + now.strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = build_report_snapshot(report, timestamp, identifier)

    history = []
    if history_path is not None:
        history_payload = Path(history_path).read_text(encoding="utf-8")
        history = deserialize_report_history(history_payload)
    updated_history = append_report_snapshot(history, snapshot)
    return serialize_report_history(updated_history)


def main(argv=None, stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = argparse.ArgumentParser(
        description="Read-only export of legacy paper_state.json for the dashboard."
    )
    parser.add_argument("--input", required=True, help="Path to data/paper_state.json")
    parser.add_argument("--marks", help="JSON object of USDT mark prices keyed by BASE or symbol")
    parser.add_argument(
        "--history", help="Optional existing dashboard history JSON; it is read only"
    )
    args = parser.parse_args(argv)
    try:
        payload = export_state_json(args.input, args.marks, history_path=args.history)
    except (OSError, ValueError, TypeError) as exc:
        print(f"Export refused: {exc}", file=stderr)
        return 2
    stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
