
import json
from collections import Counter

from historical_data import download_historical_candles
from backtest import simulate


def average(values):
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def analyze_range(trades):
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
        "expectancy_pct": average(returns),
        "profit_factor_diagnostic": round(
            positive / negative, 3
        ) if negative else None,
        "average_rsi": average([t["rsi"] for t in trades]),
        "average_ema_distance_pct": average(
            [t["ema_distance_pct"] for t in trades]
        ),
        "average_atr_pct": average(
            [t["atr_pct"] for t in trades]
        )
    }


def group_by_range(trades, field, ranges):
    results = {}

    for label, lower, upper in ranges:
        selected = [
            t for t in trades
            if lower <= t[field] < upper
        ]

        results[label] = analyze_range(selected)

    return results


def main():
    candles = download_historical_candles(days=180)

    split = int(len(candles) * 0.70)

    training = simulate(candles, 100, split - 1)
    validation = simulate(
        candles, split, len(candles) - 1
    )

    rsi_ranges = [
        ("30-35", 30, 35),
        ("35-40", 35, 40),
        ("40-45", 40, 45),
        ("55-60", 55, 60),
        ("60-65", 60, 65),
        ("65-70", 65, 70)
    ]

    ema_ranges = [
        ("below_-1.5", -100, -1.5),
        ("-1.5_to_-1.0", -1.5, -1.0),
        ("-1.0_to_-0.5", -1.0, -0.5),
        ("-0.5_to_0", -0.5, 0),
        ("0_to_0.5", 0, 0.5),
        ("0.5_to_1.0", 0.5, 1.0),
        ("1.0_to_1.5", 1.0, 1.5),
        ("above_1.5", 1.5, 100)
    ]

    atr_ranges = [
        ("low_below_0.4", 0, 0.4),
        ("medium_0.4_to_0.6", 0.4, 0.6),
        ("high_0.6_to_0.8", 0.6, 0.8),
        ("very_high_above_0.8", 0.8, 100)
    ]

    result = {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "training": {},
        "validation": {},
        "note": (
            "Exploratory ranges only. Small groups are not "
            "reliable evidence of a profitable strategy."
        )
    }

    for period_name, trades in [
        ("training", training),
        ("validation", validation)
    ]:
        result[period_name] = {}

        for direction in ["BUY", "SELL"]:
            selected = [
                t for t in trades
                if t["signal"] == direction
            ]

            result[period_name][direction] = {
                "by_rsi": group_by_range(
                    selected, "rsi", rsi_ranges
                ),
                "by_ema_distance": group_by_range(
                    selected, "ema_distance_pct", ema_ranges
                ),
                "by_atr": group_by_range(
                    selected, "atr_pct", atr_ranges
                )
            }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
