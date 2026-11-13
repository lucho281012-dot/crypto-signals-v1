"""Read-only check of Kraken 5m candle coverage versus saved paper state.

This script fetches market candles and reads data/paper_state.json. It never
opens/closes simulated positions and never writes or modifies state.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from market_data import SYMBOLS, get_candles

STATE_PATH = Path("data/paper_state.json")
TIMEFRAME_MS = 5 * 60 * 1000


def utc_from_ms(value):
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def main():
    if not STATE_PATH.exists():
        raise SystemExit(f"State file not found: {STATE_PATH}")

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    processed = state.get("last_processed_candle", {})

    print("READ-ONLY CANDLE GAP AUDIT")
    print("Timeframe: 5m | Uses latest closed candle (same convention as paper_bot.py)")
    print("No simulated orders will be placed and no files will be changed.")

    failures = []
    for symbol in SYMBOLS:
        candles = get_candles(symbol, timeframe="5m", limit=250)
        if len(candles) < 3:
            print(f"{symbol}: INSUFFICIENT_DATA ({len(candles)} candles)")
            failures.append(f"{symbol}: fewer than 3 candles returned")
            continue

        first_ts = int(candles[0]["timestamp"])
        latest_closed_ts = int(candles[-2]["timestamp"])
        saved_raw = processed.get(symbol)

        if saved_raw is None:
            print(f"{symbol}: NO_SAVED_CHECKPOINT; available "
                  f"{utc_from_ms(first_ts)} to {utc_from_ms(latest_closed_ts)}")
            continue

        saved_ts = int(saved_raw)
        missing_bars = max(0, (latest_closed_ts - saved_ts) // TIMEFRAME_MS - 1)
        checkpoint_is_available = first_ts <= saved_ts <= latest_closed_ts

        if saved_ts > latest_closed_ts:
            status = "CHECKPOINT_AHEAD_OF_MARKET_DATA"
            failures.append(f"{symbol}: saved checkpoint is newer than latest closed candle")
        elif saved_ts < first_ts:
            status = "GAP_EXCEEDS_250_CANDLE_WINDOW"
            failures.append(f"{symbol}: saved checkpoint predates available candle history")
        elif missing_bars == 0:
            status = "UP_TO_DATE"
        else:
            status = "GAP_WITHIN_AVAILABLE_WINDOW"
            failures.append(f"{symbol}: {missing_bars} unprocessed 5m candles")

        print(
            f"{symbol}: {status} | saved={utc_from_ms(saved_ts)} | "
            f"oldest_available={utc_from_ms(first_ts)} | "
            f"latest_closed={utc_from_ms(latest_closed_ts)} | "
            f"unprocessed_intervals={missing_bars}"
        )

    if failures:
        print("AUDIT: ATTENTION REQUIRED")
        for item in failures:
            print(f"- {item}")
        print("Do not run paper_bot.py to catch up until the gap and position "
              "stop/target history have been reviewed.")
    else:
        print("AUDIT: no candle gap detected for symbols with saved checkpoints.")


if __name__ == "__main__":
    main()
