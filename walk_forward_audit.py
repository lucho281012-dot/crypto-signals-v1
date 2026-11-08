
import json

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

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(
            len(wins) / len(trades) * 100, 2
        ),
        "expectancy_pct": round(
            sum(returns) / len(returns), 4
        ),
        "profit_factor_diagnostic": round(
            gross_profit / gross_loss, 3
        ) if gross_loss else None
    }


def main():
    candles = download_historical_candles(days=365)

    total = len(candles)

    if total < 1000:
        print(json.dumps({
            "status": "insufficient_data",
            "candles": total,
            "message": "Need at least 1000 candles."
        }, indent=2))
        return

    warmup = 100
    usable = total - warmup
    block_size = usable // 4

    results = {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candles": total,
        "method": "Four chronological evaluation blocks",
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
            "start_index": start,
            "end_index": end,
            "BUY": summarize([
                t for t in trades if t["signal"] == "BUY"
            ]),
            "SELL": summarize([
                t for t in trades if t["signal"] == "SELL"
            ]),
            "ALL": summarize(trades)
        }

        results["blocks"].append(block_result)

    results["note"] = (
        "Exploratory robustness audit. These are chronological "
        "historical blocks, not independent future results. "
        "No trading rules were changed."
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
