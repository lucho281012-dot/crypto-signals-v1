"""Portfolio accounting, risk-limit and per-symbol paper-trading report."""
import json
from datetime import datetime
from pathlib import Path

from paper_trading import (
    FEE_RATE,
    MAX_AGGREGATE_RISK_PERCENT,
    MAX_POSITION_PERCENT,
    get_status,
)

STATE_FILE = Path("data/paper_state.json")
TOLERANCE = 1e-7


def summarize(trades):
    wins = [float(t["net_pnl"]) for t in trades if float(t["net_pnl"]) > 0]
    losses = [float(t["net_pnl"]) for t in trades if float(t["net_pnl"]) < 0]
    total = sum(float(t["net_pnl"]) for t in trades)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else 0.0,
        "net_pnl_usdt": round(total, 6),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
    }


def audit_portfolio(state):
    """Check ledger reconciliation and the configured capital constraints."""
    status = get_status(state)
    initial = float(state["initial_balance"])
    realized = sum(float(t.get("net_pnl", 0)) for t in state.get("history", []))
    open_cost_and_fees = sum(
        float(p["quantity"]) * float(p["entry_price"]) + float(p.get("entry_fee", 0))
        for p in state.get("positions", {}).values()
    )
    expected_cash = initial + realized - open_cost_and_fees
    cash_residual = float(state["cash_usdt"]) - expected_cash
    invested = sum(
        float(p["quantity"]) * float(p["entry_price"])
        for p in state.get("positions", {}).values()
    )
    open_risk = sum(
        float(p.get("risk_budget", 0))
        for p in state.get("positions", {}).values()
    )
    equity_residual = status["total_pnl"] - (
        status["realized_pnl"] + status["unrealized_pnl"]
    )

    checks = {
        "cash_ledger_reconciles": abs(cash_residual) <= TOLERANCE,
        "equity_pnl_reconciles": abs(equity_residual) <= TOLERANCE,
        "investment_limit_respected": invested <= initial * MAX_POSITION_PERCENT + TOLERANCE,
        "aggregate_risk_limit_respected": open_risk <= initial * MAX_AGGREGATE_RISK_PERCENT + TOLERANCE,
        "cash_non_negative": float(state["cash_usdt"]) >= -TOLERANCE,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "cash_reconciliation_residual_usdt": round(cash_residual, 8),
        "equity_reconciliation_residual_usdt": round(equity_residual, 8),
        "investment_limit_usdt": round(initial * MAX_POSITION_PERCENT, 4),
        "aggregate_risk_limit_usdt": round(initial * MAX_AGGREGATE_RISK_PERCENT, 4),
        "fee_rate_per_side": FEE_RATE,
    }


def build_report(state):
    history = state.get("history", [])
    baseline_raw = state.get("baseline_metadata", {}).get("created_at")
    baseline = datetime.fromisoformat(baseline_raw) if baseline_raw else None
    symbols = sorted({trade.get("symbol", "UNKNOWN") for trade in history})
    report = {
        "baseline_created_at": baseline_raw,
        "portfolio": get_status(state),
        "audit": audit_portfolio(state),
        "by_symbol": {},
    }

    for symbol in symbols:
        trades = [t for t in history if t.get("symbol", "UNKNOWN") == symbol]
        post_baseline = []
        for trade in trades:
            opened = trade.get("opened_at")
            if baseline and opened:
                opened_at = datetime.fromisoformat(opened)
                if opened_at >= baseline:
                    post_baseline.append(trade)
        report["by_symbol"][symbol] = {
            "all_time": summarize(trades),
            "since_baseline": summarize(post_baseline),
        }
    return report


def main():
    with STATE_FILE.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    print(json.dumps(build_report(state), indent=2))
    if not audit_portfolio(state)["passed"]:
        raise SystemExit("La auditoría financiera detectó una inconsistencia.")


if __name__ == "__main__":
    main()
