"""Read-only CSV export and trend summaries for paper report history.

All functions are pure: they do not read/write files, access networks, or trade.
"""
import csv
from decimal import Decimal, InvalidOperation
import io
import json

from paper_report_history import validate_report_history


_REPORT_COLUMNS = (
    "quote_currency",
    "initial_cash_usdt",
    "cash_usdt",
    "market_value_usdt",
    "equity_usdt",
    "total_pnl_usdt",
    "total_return_pct",
    "realized_pnl_usdt",
    "unrealized_pnl_usdt",
    "fees_paid_usdt",
    "trade_count",
    "buy_count",
    "sell_count",
    "open_position_count",
)
_CSV_COLUMNS = (
    "snapshot_id",
    "captured_at",
    *_REPORT_COLUMNS,
    "positions_json",
)


def _spreadsheet_safe_text(value):
    """Prefix risky textual cells so spreadsheet apps do not treat them as formulas."""
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def export_report_history_csv(history):
    """Return deterministic CSV text with one row per validated snapshot."""
    validate_report_history(history)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for snapshot in history:
        report = snapshot["report"]
        row = {
            "snapshot_id": _spreadsheet_safe_text(snapshot["snapshot_id"]),
            "captured_at": snapshot["captured_at"],
            "positions_json": json.dumps(
                report.get("positions", {}),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        }
        for column in _REPORT_COLUMNS:
            value = report.get(column, "")
            row[column] = (
                _spreadsheet_safe_text(value)
                if column == "quote_currency" and value != ""
                else value
            )
        writer.writerow(row)
    return output.getvalue()


def _finite_decimal(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def build_report_history_summary(history):
    """Summarize equity movement across snapshots without changing the history."""
    validate_report_history(history)
    if not history:
        return {
            "snapshot_count": 0,
            "first_captured_at": None,
            "latest_captured_at": None,
            "first_equity_usdt": None,
            "latest_equity_usdt": None,
            "equity_change_usdt": None,
            "latest_total_pnl_usdt": None,
            "latest_total_return_pct": None,
            "highest_equity_usdt": None,
            "lowest_equity_usdt": None,
        }

    equities = [
        _finite_decimal(item["report"].get("equity_usdt"), f"history[{index}].equity_usdt")
        for index, item in enumerate(history)
    ]
    latest_report = history[-1]["report"]
    latest_pnl = _finite_decimal(
        latest_report.get("total_pnl_usdt"), "latest.total_pnl_usdt"
    )
    latest_return = _finite_decimal(
        latest_report.get("total_return_pct"), "latest.total_return_pct"
    )
    return {
        "snapshot_count": len(history),
        "first_captured_at": history[0]["captured_at"],
        "latest_captured_at": history[-1]["captured_at"],
        "first_equity_usdt": str(equities[0]),
        "latest_equity_usdt": str(equities[-1]),
        "equity_change_usdt": str(equities[-1] - equities[0]),
        "latest_total_pnl_usdt": str(latest_pnl),
        "latest_total_return_pct": str(latest_return),
        "highest_equity_usdt": str(max(equities)),
        "lowest_equity_usdt": str(min(equities)),
    }
