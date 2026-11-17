"""Descriptive audit of closed paper trades; never changes strategy or paper state."""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

STATE_FILE = Path("data/paper_state.json")
TOLERANCE = 1e-8


def _duration_minutes(start, end):
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0.0, (b - a).total_seconds() / 60.0)
    except (TypeError, ValueError):
        return None


def build_quality_report(state):
    trades = list(state.get("history", []))
    by_symbol = defaultdict(list)
    by_reason = defaultdict(list)
    rows = []
    missing_context = 0
    pnl_mismatches = []
    total_fees = 0.0

    for index, trade in enumerate(trades):
        required = ("quantity", "entry_price", "exit_price", "net_pnl")
        if any(key not in trade for key in required):
            missing_context += 1
            continue
        quantity = float(trade["quantity"])
        entry = float(trade["entry_price"])
        exit_price = float(trade["exit_price"])
        entry_fee = float(trade.get("entry_fee", 0.0))
        exit_fee = float(trade.get("exit_fee", 0.0))
        pnl = float(trade["net_pnl"])
        fees = entry_fee + exit_fee
        total_fees += fees
        recomputed = quantity * (exit_price - entry) - fees
        if abs(pnl - recomputed) > TOLERANCE:
            pnl_mismatches.append({
                "trade_index": index,
                "symbol": trade.get("symbol", "UNKNOWN"),
                "recorded_net_pnl": pnl,
                "recomputed_net_pnl": recomputed,
                "difference": pnl - recomputed,
            })

        stop = float(trade.get("stop_price", 0.0) or 0.0)
        # Prefer the risk budget captured by the simulator at entry; it
        # already includes estimated round-trip fees and any balance cap.
        risk = float(trade.get("risk_budget", 0.0) or 0.0)
        if risk <= 0 and stop > 0 and entry > stop:
            risk = quantity * (entry - stop) + entry_fee + (
                quantity * stop * (exit_fee / (quantity * exit_price))
                if exit_price > 0 else 0.0
            )
        if risk <= 0:
            risk = None
        r_multiple = pnl / risk if risk and risk > 0 else None
        duration = _duration_minutes(trade.get("opened_at"), trade.get("closed_at"))
        row = {
            "symbol": trade.get("symbol", "UNKNOWN"),
            "reason": trade.get("reason", "UNKNOWN"),
            "net_pnl_usdt": pnl,
            "fees_usdt": fees,
            "r_multiple": r_multiple,
            "holding_minutes": duration,
            "has_entry_signal_context": bool(
                trade.get("signal_diagnostic") or trade.get("signal_metadata")
            ),
        }
        rows.append(row)
        by_symbol[row["symbol"]].append(row)
        by_reason[row["reason"]].append(row)

    def summarize(items):
        values = [item["net_pnl_usdt"] for item in items]
        wins = [v for v in values if v > 0]
        losses = [v for v in values if v < 0]
        gross_profit = sum(wins)
        gross_loss = -sum(losses)
        durations = [x["holding_minutes"] for x in items if x["holding_minutes"] is not None]
        rs = [x["r_multiple"] for x in items if x["r_multiple"] is not None]
        return {
            "trades": len(items),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_percent": round(100 * len(wins) / len(items), 4) if items else None,
            "net_pnl_usdt": round(sum(values), 8),
            "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
            "expectancy_usdt": round(sum(values) / len(values), 8) if values else None,
            "fees_usdt": round(sum(x["fees_usdt"] for x in items), 8),
            "average_holding_minutes": round(sum(durations) / len(durations), 4) if durations else None,
            "average_r_multiple": round(sum(rs) / len(rs), 6) if rs else None,
        }

    return {
        "closed_trade_summary": summarize(rows),
        "by_symbol": {key: summarize(value) for key, value in sorted(by_symbol.items())},
        "by_exit_reason": {key: summarize(value) for key, value in sorted(by_reason.items())},
        "closed_trades_with_entry_context": sum(x["has_entry_signal_context"] for x in rows),
        "closed_trades_missing_entry_context": sum(not x["has_entry_signal_context"] for x in rows),
        "records_skipped_missing_required_fields": missing_context,
        "pnl_mismatches": pnl_mismatches,
        "open_positions_not_scored": len(state.get("positions", {})),
        "trade_details": rows,
        "limitations": [
            "Descriptive statistics only; the sample is not proof of a persistent trading edge.",
            "Historical trades without stored entry diagnostics cannot be attributed to indicator conditions.",
            "Open positions are excluded from closed-trade performance.",
            "No slippage or spread estimate is added beyond costs already recorded in the paper ledger.",
        ],
    }


def main():
    with STATE_FILE.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    report = build_quality_report(state)
    print(json.dumps(report, indent=2))
    if report["pnl_mismatches"] or report["records_skipped_missing_required_fields"]:
        raise SystemExit("Trade quality audit found ledger inconsistencies.")


if __name__ == "__main__":
    main()
