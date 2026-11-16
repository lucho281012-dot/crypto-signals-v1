"""Persist Kraken closed OHLC candles locally in the repository for research.

This collector is read-only: it never places orders and never touches paper_state.json.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
TIMEFRAMES = {"5m": 300_000, "15m": 900_000}
MAX_CANDLES = 720
DATA_DIR = Path("data/market_history")


def safe_symbol(symbol):
    return symbol.replace("/", "_").replace(":", "_")


def archive_path(symbol, timeframe):
    return DATA_DIR / f"{safe_symbol(symbol)}_{timeframe}.jsonl"


def load_archive(path):
    candles = {}
    if not path.exists():
        return candles
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            candle = json.loads(line)
            timestamp = int(candle["timestamp"])
            candles[timestamp] = {
                "timestamp": timestamp,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle["volume"]),
            }
    return candles


def fetch_closed_candles(exchange, symbol, timeframe, since=None):
    interval = TIMEFRAMES[timeframe]
    params = {"timeframe": timeframe, "limit": MAX_CANDLES}
    if since is not None:
        params["since"] = int(since)
    raw = exchange.fetch_ohlcv(symbol, **params)
    now = exchange.milliseconds()
    result = []
    for row in raw:
        timestamp = int(row[0])
        if timestamp + interval > now:
            continue
        result.append({
            "timestamp": timestamp,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })
    return result


def collect_one(exchange, symbol, timeframe):
    path = archive_path(symbol, timeframe)
    existing = load_archive(path)
    latest = max(existing) if existing else None
    # On first run, seed with Kraken's latest 720 entries. Thereafter request
    # only candles newer than the last archived candle.
    since = latest + TIMEFRAMES[timeframe] if latest is not None else None
    fetched = fetch_closed_candles(exchange, symbol, timeframe, since=since)
    before = len(existing)
    for candle in fetched:
        existing[candle["timestamp"]] = candle
    ordered = [existing[key] for key in sorted(existing)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for candle in ordered:
            handle.write(json.dumps(candle, separators=(",", ":")) + "\n")
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "new_candles": len(existing) - before,
        "total_candles": len(ordered),
        "first_timestamp": ordered[0]["timestamp"] if ordered else None,
        "last_timestamp": ordered[-1]["timestamp"] if ordered else None,
        "file": str(path),
    }


def main():
    exchange = ccxt.kraken({"enableRateLimit": True})
    exchange.load_markets()
    results = []
    for symbol in SYMBOLS:
        if symbol not in exchange.markets:
            results.append({"symbol": symbol, "error": "Pair unavailable on Kraken"})
            continue
        for timeframe in TIMEFRAMES:
            try:
                results.append(collect_one(exchange, symbol, timeframe))
                time.sleep(exchange.rateLimit / 1000)
            except Exception as error:
                results.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "error": str(error),
                })
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_market_data_collection",
        "results": results,
    }
    print(json.dumps(report, indent=2))
    if any("error" in item for item in results):
        raise SystemExit("One or more market-history collections failed")


if __name__ == "__main__":
    main()
