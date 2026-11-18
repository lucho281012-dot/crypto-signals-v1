"""Persist closed Kraken OHLC candles and report archive continuity.

Read-only market-data collection: no orders, credentials, or paper-state access.
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
FIELDS = ("timestamp", "open", "high", "low", "close", "volume")


def safe_symbol(symbol):
    return symbol.replace("/", "_").replace(":", "_")


def archive_path(symbol, timeframe):
    return DATA_DIR / f"{safe_symbol(symbol)}_{timeframe}.jsonl"


def validate_candle(candle, interval):
    row = {key: candle[key] for key in FIELDS}
    row["timestamp"] = int(row["timestamp"])
    for key in ("open", "high", "low", "close", "volume"):
        row[key] = float(row[key])
    if row["timestamp"] % interval:
        raise ValueError(f"Timestamp not aligned to {interval}ms: {row['timestamp']}")
    if any(not __import__("math").isfinite(row[key]) for key in FIELDS[1:]):
        raise ValueError("Candle contains non-finite OHLCV values")
    if min(row[k] for k in ("open", "high", "low", "close")) <= 0 or row["volume"] < 0:
        raise ValueError("Candle has non-positive prices or negative volume")
    if row["high"] < max(row["open"], row["close"], row["low"]):
        raise ValueError("Invalid candle high")
    if row["low"] > min(row["open"], row["close"], row["high"]):
        raise ValueError("Invalid candle low")
    return row


def load_archive(path, interval):
    candles = {}
    if not path.exists():
        return candles
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                candle = validate_candle(json.loads(line), interval)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"Invalid archive row {line_number} in {path}: {error}") from error
            candles[candle["timestamp"]] = candle
    return candles


def find_gaps(timestamps, interval):
    ordered = sorted(set(int(ts) for ts in timestamps))
    gaps = []
    for previous, current in zip(ordered, ordered[1:]):
        missing = (current - previous) // interval - 1
        if current - previous != interval:
            if current <= previous or (current - previous) % interval:
                gaps.append({"after": previous, "before": current, "missing_candles": None})
            elif missing > 0:
                gaps.append({"after": previous, "before": current, "missing_candles": missing})
    return gaps


def fetch_closed_candles(exchange, symbol, timeframe, since=None):
    interval = TIMEFRAMES[timeframe]
    params = {"timeframe": timeframe, "limit": MAX_CANDLES}
    if since is not None:
        params["since"] = int(since)
    raw = exchange.fetch_ohlcv(symbol, **params)
    now = exchange.milliseconds()
    result = []
    for row in raw:
        candle = validate_candle({
            "timestamp": row[0], "open": row[1], "high": row[2],
            "low": row[3], "close": row[4], "volume": row[5],
        }, interval)
        if candle["timestamp"] + interval <= now:
            result.append(candle)
    return sorted(result, key=lambda item: item["timestamp"])


def collect_one(exchange, symbol, timeframe):
    interval = TIMEFRAMES[timeframe]
    path = archive_path(symbol, timeframe)
    existing = load_archive(path, interval)
    latest = max(existing) if existing else None
    since = latest + interval if latest is not None else None
    fetched = fetch_closed_candles(exchange, symbol, timeframe, since=since)
    before = len(existing)
    for candle in fetched:
        existing[candle["timestamp"]] = candle
    ordered = [existing[key] for key in sorted(existing)]
    gaps = find_gaps(existing, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for candle in ordered:
            handle.write(json.dumps(candle, separators=(",", ":")) + "\n")
    return {
        "symbol": symbol, "timeframe": timeframe,
        "new_candles": len(existing) - before, "total_candles": len(ordered),
        "first_timestamp": ordered[0]["timestamp"] if ordered else None,
        "last_timestamp": ordered[-1]["timestamp"] if ordered else None,
        "gap_count": len(gaps),
        "missing_candles_estimate": (
            sum(gap["missing_candles"] for gap in gaps
                if gap["missing_candles"] is not None)
            if all(gap["missing_candles"] is not None for gap in gaps) else None
        ),
        "first_gap": gaps[0] if gaps else None,
        "continuous": not gaps,
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
                results.append({"symbol": symbol, "timeframe": timeframe, "error": str(error)})
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_market_data_collection",
        "results": results,
        "note": "Kraken OHLC endpoint is capped at 720 returned candles; detected historical gaps are reported, not silently repaired.",
    }
    print(json.dumps(report, indent=2))
    if any("error" in item for item in results):
        raise SystemExit("One or more market-history collections failed")


if __name__ == "__main__":
    main()
