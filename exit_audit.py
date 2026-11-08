
import json
from collections import defaultdict

from historical_data import download_historical_candles
from backtest import simulate


def summarize(trades):
    if not trades:
        return {
            "trades": 0,
            "message": "No trades"
        }

    returns = [t["net_return_pct"] for t in trades]

    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(
            len(wins) / len(trades) * 100, 2
        ),
        "average_net_return_pct": round(
            sum(returns) / len(returns), 4
        ),
        "total_net_return_pct": round(
            sum(returns), 4
        )
    }


def analyze_exits(trades):
    groups = defaultdict(list)

    for trade in trades:
        reason = trade.get(
            "exit_reason",
            trade.get("reason", "UNKNOWN")
        )
        groups[reason].append(trade)

    return {
        reason: summarize(group)
        for reason, group in sorted(groups.items())
    }


def main():
    candles = download_historical_candles(days=365)

    total = len(candles)
    warmup = 100

    if total < 1000:
        print(json.dumps({
            "status": "insufficient_data",
            "candles": total
        }, indent=2))
        return

    usable = total - warmup
    block_size = usable // 4

    results = {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candles": total,
        "blocks": []
    }

    for block in range(4):
        start = warmup + block * block_size

        if block == 3:
            end = total - 1
        else:
            end = warmup + (block + 1) * block_size - 1

        trades = simulate(candles, start, end)

        block_result = {
            "block": block + 1,
            "ALL": analyze_exits(trades),
            "BUY": analyze_exits([
                t for t in trades if t["signal"] == "BUY"
            ]),
            "SELL": analyze_exits([
                t for t in trades if t["signal"] == "SELL"
            ])
        }

        results["blocks"].append(block_result)

    results["note"] = (
        "Exit analysis is diagnostic. UNKNOWN means "
        "the trade did not contain a recognized exit reason."
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
