
import json
from collections import defaultdict

from historical_data import download_historical_candles
from backtest import simulate


def average(values):
    if not values:
        return None

    return round(sum(values) / len(values), 4)


def analyze_group(trades):
    if not trades:
        return {
            "trades": 0,
            "message": "No trades"
        }

    wins = [
        t for t in trades
        if t["net_return_pct"] > 0
    ]

    losses = [
        t for t in trades
        if t["net_return_pct"] < 0
    ]

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(
            len(wins) / len(trades) * 100, 2
        ),
        "average_rsi": average([
            t["rsi"] for t in trades
        ]),
        "average_ema_distance_pct": average([
            t["ema_distance_pct"] for t in trades
        ]),
        "average_atr_pct": average([
            t["atr_pct"] for t in trades
        ]),
        "average_return_pct": average([
            t["net_return_pct"] for t in trades
        ])
    }


def analyze_direction(trades):
    outcomes = defaultdict(list)
    exits = defaultdict(list)

    for trade in trades:
        if trade["net_return_pct"] > 0:
            outcomes["WINS"].append(trade)

        elif trade["net_return_pct"] < 0:
            outcomes["LOSSES"].append(trade)

        exits[trade["reason"]].append(trade)

    return {
        "overall": analyze_group(trades),
        "outcomes": {
            name: analyze_group(group)
            for name, group in sorted(outcomes.items())
        },
        "exits": {
            name: analyze_group(group)
            for name, group in sorted(exits.items())
        }
    }


def validate_block(trades, buy_trades, sell_trades):
    total = len(trades)
    buy_total = len(buy_trades)
    sell_total = len(sell_trades)

    unknown = [
        t for t in trades
        if t["signal"] not in ("BUY", "SELL")
    ]

    exit_counts = defaultdict(int)

    for trade in trades:
        exit_counts[trade["reason"]] += 1

    return {
        "total_trades": total,
        "buy_trades": buy_total,
        "sell_trades": sell_total,
        "unknown_direction": len(unknown),
        "directions_reconcile": (
            total == buy_total + sell_total
        ),
        "exit_counts": dict(sorted(exit_counts.items())),
        "exits_reconcile": (
            sum(exit_counts.values()) == total
        )
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

        buy_trades = [
            t for t in trades
            if t["signal"] == "BUY"
        ]

        sell_trades = [
            t for t in trades
            if t["signal"] == "SELL"
        ]

        block_result = {
            "block": block + 1,
            "validation": validate_block(
                trades,
                buy_trades,
                sell_trades
            ),
            "BUY": analyze_direction(buy_trades),
            "SELL": analyze_direction(sell_trades)
        }

        results["blocks"].append(block_result)

    results["note"] = (
        "Diagnostic only. WINS and LOSSES are grouped "
        "by net return. No trading rules were changed."
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
