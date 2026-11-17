"""Show all-time and post-baseline paper-trading statistics per symbol."""
import json
from datetime import datetime
from pathlib import Path

STATE_FILE = Path("data/paper_state.json")


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


def build_report(state):
    history = state.get("history", [])
    baseline_raw = state.get("baseline_metadata", {}).get("created_at")
    baseline = datetime.fromisoformat(baseline_raw) if baseline_raw else None
    symbols = sorted({trade.get("symbol", "UNKNOWN") for trade in history})
    report = {"baseline_created_at": baseline_raw, "by_symbol": {}}

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


if __name__ == "__main__":
    main()
