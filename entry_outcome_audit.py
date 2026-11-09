
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
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "message": "No trades"
        }

    wins = [
        trade for trade in trades
        if trade["net_return_pct"] > 0
    ]

    losses = [
        trade for trade in trades
        if trade["net_return_pct"] < 0
    ]

    breakeven = [
        trade for trade in trades
        if trade["net_return_pct"] == 0
    ]

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate_pct": round(
            len(wins) / len(trades) * 100, 2
        ),
        "average_rsi": average([
            trade["rsi"] for trade in trades
        ]),
        "average_ema_distance_pct": average([
            trade["ema_distance_pct"] for trade in trades
        ]),
        "average_atr_pct": average([
            trade["atr_pct"] for trade in trades
        ]),
        "average_return_pct": average([
            trade["net_return_pct"] for trade in trades
        ])
    }


def analyze_direction(trades):
    outcomes = defaultdict(list)
    exits = defaultdict(list)

    for trade in trades:
        result = trade["net_return_pct"]

        if result > 0:
            outcomes["WINS"].append(trade)

        elif result < 0:
            outcomes["LOSSES"].append(trade)

        else:
            outcomes["BREAKEVEN"].append(trade)

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
        trade for trade in trades
        if trade["signal"] not in ("BUY", "SELL")
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
            end = (
                warmup
                + (block + 1) * block_size
                - 1
            )

        trades = simulate(candles, start, end)

        buy_trades = [
            trade for trade in trades
            if trade["signal"] == "BUY"
        ]

        sell_trades = [
            trade for trade in trades
            if trade["signal"] == "SELL"
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
        "Diagnostic only. Outcomes include WINS, "
        "LOSSES and BREAKEVEN. No trading rules changed."
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
