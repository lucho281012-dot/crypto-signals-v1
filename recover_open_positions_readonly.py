"""Read-only reconstruction of open paper positions from Kraken trade history.

Uses Kraken's public Trades endpoint, paginates with the returned nanosecond
cursor, and rebuilds 5-minute OHLC bars in memory. It never writes files,
places orders, or changes data/paper_state.json.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt

STATE_PATH = Path("data/paper_state.json")
TIMEFRAME_SECONDS = 300
MAX_PAGES_PER_SYMBOL = 500


def parse_utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def candle_start(timestamp_seconds):
    return int(timestamp_seconds // TIMEFRAME_SECONDS) * TIMEFRAME_SECONDS


def main():
    if not STATE_PATH.exists():
        raise SystemExit(f"State file not found: {STATE_PATH}")

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    positions = state.get("positions", {})
    if not positions:
        print("No open positions to reconstruct.")
        return

    exchange = ccxt.kraken({"enableRateLimit": True})
    exchange.load_markets()

    now_seconds = datetime.now(timezone.utc).timestamp()
    # Match paper_bot.py: inspect only fully closed 5-minute candles.
    end_exclusive = int(now_seconds // TIMEFRAME_SECONDS) * TIMEFRAME_SECONDS

    print("READ-ONLY POSITION RECOVERY")
    print("Source: Kraken public Trades endpoint (actual trade prints)")
    print("Method: rebuild 5m OHLC bars; apply paper_bot.py stop-first logic")
    print("No orders, no state writes, no simulated position changes.")
    print(f"Closed-candle data boundary: {datetime.fromtimestamp(end_exclusive, timezone.utc).isoformat()}")

    for symbol, position in positions.items():
        if symbol not in exchange.markets:
            print(f"{symbol}: MARKET_NOT_AVAILABLE_ON_KRAKEN")
            continue

        opened_at = parse_utc(position["opened_at"])
        start_ns = int(opened_at.timestamp() * 1_000_000_000)
        cursor = str(start_ns)
        market_id = exchange.market(symbol)["id"]
        bars = {}
        pages = 0
        trade_count = 0
        first_trade = None
        last_trade = None
        reached_end = False

        print(f"\n{symbol}: requesting trades since {opened_at.isoformat()}")

        while pages < MAX_PAGES_PER_SYMBOL:
            response = exchange.publicGetTrades({"pair": market_id, "since": cursor})
            errors = response.get("error") or []
            if errors:
                raise RuntimeError(f"{symbol}: Kraken API error: {errors}")

            result = response.get("result") or {}
            next_cursor = str(result.get("last", ""))
            pair_keys = [key for key in result.keys() if key != "last"]
            if not pair_keys:
                break

            rows = result[pair_keys[0]]
            if not rows:
                break

            pages += 1
            page_max_ts = 0.0

            for trade in rows:
                price = float(trade[0])
                amount = float(trade[1])
                timestamp = float(trade[2])
                page_max_ts = max(page_max_ts, timestamp)

                if timestamp < opened_at.timestamp() or timestamp >= end_exclusive:
                    continue

                bucket = candle_start(timestamp)
                bar = bars.get(bucket)
                if bar is None:
                    bars[bucket] = {
                        "timestamp": bucket,
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": amount,
                        "trades": 1,
                    }
                else:
                    bar["high"] = max(bar["high"], price)
                    bar["low"] = min(bar["low"], price)
                    bar["close"] = price
                    bar["volume"] += amount
                    bar["trades"] += 1

                trade_count += 1
                if first_trade is None:
                    first_trade = timestamp
                last_trade = timestamp

            if page_max_ts >= end_exclusive:
                reached_end = True
                break

            if not next_cursor or next_cursor == cursor:
                break

            cursor = next_cursor
            # Kraken's returned cursor is the pagination token; CCXT rate
            # limiting is enabled on the exchange instance.
            if len(rows) < 1000:
                reached_end = True
                break

        if pages >= MAX_PAGES_PER_SYMBOL and not reached_end:
            raise RuntimeError(
                f"{symbol}: hit MAX_PAGES_PER_SYMBOL; history may be incomplete. "
                "Do not use this partial reconstruction."
            )

        ordered_bars = [bars[key] for key in sorted(bars)]
        stop = float(position["stop_price"])
        target = position.get("target_price")
        target = float(target) if target is not None else None
        event = None

        for bar in ordered_bars:
            stop_hit = bar["low"] <= stop
            target_hit = target is not None and bar["high"] >= target
            if stop_hit:
                event = {
                    "time": datetime.fromtimestamp(bar["timestamp"], timezone.utc).isoformat(),
                    "bar_open": bar["open"],
                    "bar_low": bar["low"],
                    "bar_high": bar["high"],
                    "exit_price": min(bar["open"], stop),
                    "reason": "stop_loss",
                    "both_levels_touched": bool(target_hit),
                    "bar_trades": bar["trades"],
                }
                break
            if target_hit:
                event = {
                    "time": datetime.fromtimestamp(bar["timestamp"], timezone.utc).isoformat(),
                    "bar_open": bar["open"],
                    "bar_low": bar["low"],
                    "bar_high": bar["high"],
                    "exit_price": max(bar["open"], target),
                    "reason": "take_profit",
                    "both_levels_touched": False,
                    "bar_trades": bar["trades"],
                }
                break

        print(
            f"  pages={pages} trades={trade_count} rebuilt_5m_bars={len(ordered_bars)} "
            f"first_trade={datetime.fromtimestamp(first_trade, timezone.utc).isoformat() if first_trade else 'none'} "
            f"last_trade={datetime.fromtimestamp(last_trade, timezone.utc).isoformat() if last_trade else 'none'}"
        )

        if not reached_end:
            print("  COVERAGE_WARNING: pagination did not prove coverage through the closed-candle boundary.")
            print("  RESULT_WITHHELD: do not infer that no stop/target was hit.")
        elif event:
            print("  FIRST_TRIGGER_FOUND:")
            print(json.dumps(event, indent=2))
            if event["both_levels_touched"]:
                print("  NOTE: both stop and target were touched in one 5m bar; paper_bot.py prioritizes stop_loss.")
        else:
            print("  NO_TRIGGER_IN_RECONSTRUCTED_TRADE_BARS through the closed-candle boundary.")

    print("\nEND: read-only reconstruction complete. Saved simulator state was not modified.")


if __name__ == "__main__":
    main()
