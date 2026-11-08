
import json
from collections import Counter

from historical_data import download_historical_candles
from backtest import simulate


def analyze_group(trades):
    if not trades:
        return {
            "trades": 0,
            "message": "No trades"
        }

    returns = [t["net_return_pct"] for t in trades]

    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]

    positive = sum(wins)
    negative = abs(sum(losses))

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(
            len(wins) / len(trades) * 100, 2
        ),
        "average_win_pct": round(
            sum(wins) / len(wins), 4
        ) if wins else 0,
        "average_loss_pct": round(
            sum(losses) / len(losses), 4
        ) if losses else 0,
        "expectancy_pct": round(
            sum(returns) / len(returns), 4
        ),
        "net_sum_pct": round(sum(returns), 4),
        "profit_factor_diagnostic": round(
            positive / negative, 3
        ) if negative else None,
        "exit_reasons": dict(
            Counter(t["reason"] for t in trades)
        )
    }


def main():
    candles = download_historical_candles(days=180)

    split = int(len(candles) * 0.70)

    training = simulate(candles, 100, split - 1)
    validation = simulate(
        candles, split, len(candles) - 1
    )

    result = {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "training": {
            "BUY": analyze_group([
                t for t in training
                if t["signal"] == "BUY"
            ]),
            "SELL": analyze_group([
                t for t in training
                if t["signal"] == "SELL"
            ])
        },
        "validation": {
            "BUY": analyze_group([
                t for t in validation
                if t["signal"] == "BUY"
            ]),
            "SELL": analyze_group([
                t for t in validation
                if t["signal"] == "SELL"
            ])
        },
        "important_note": (
            "Diagnostic metrics based on equal-sized "
            "trade percentage returns. Not proof of profitability."
        )
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
