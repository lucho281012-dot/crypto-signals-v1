
import json
import backtest

from historical_data import download_historical_candles


CONFIGURATIONS = [
    {"name": "A", "stop_atr": 1.0, "reward_risk": 2.0},
    {"name": "B_BASELINE", "stop_atr": 1.5, "reward_risk": 2.0},
    {"name": "C", "stop_atr": 2.0, "reward_risk": 2.0},
    {"name": "D", "stop_atr": 1.5, "reward_risk": 1.5},
    {"name": "E", "stop_atr": 2.0, "reward_risk": 1.5},
    {"name": "F", "stop_atr": 2.0, "reward_risk": 2.5}
]


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

    original_stop = backtest.STOP_ATR
    original_rr = backtest.REWARD_RISK

    results = {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candles": total,
        "configurations": []
    }

    try:
        for config in CONFIGURATIONS:
            backtest.STOP_ATR = config["stop_atr"]
            backtest.REWARD_RISK = config["reward_risk"]

            blocks = []
            all_trades = []

            for block in range(4):
                start = warmup + block * block_size

                if block == 3:
                    end = total - 1
                else:
                    end = (
                        warmup
                        + (block + 1) * block_size
                        - 1
                    )

                trades = backtest.simulate(
                    candles, start, end
                )

                all_trades.extend(trades)

                blocks.append({
                    "block": block + 1,
                    "ALL": backtest.summarize(trades),
                    "BUY": backtest.summarize([
                        t for t in trades
                        if t["signal"] == "BUY"
                    ]),
                    "SELL": backtest.summarize([
                        t for t in trades
                        if t["signal"] == "SELL"
                    ])
                })

            results["configurations"].append({
                "name": config["name"],
                "stop_atr": config["stop_atr"],
                "reward_risk": config["reward_risk"],
                "overall": backtest.summarize(all_trades),
                "blocks": blocks
            })

    finally:
        backtest.STOP_ATR = original_stop
        backtest.REWARD_RISK = original_rr

    results["note"] = (
        "Exploratory parameter comparison. "
        "No real orders. Compounded returns assume "
        "full capital exposure per trade and are diagnostic."
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
