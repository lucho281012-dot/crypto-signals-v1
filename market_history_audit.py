"""Validate archived OHLCV files before historical research; read-only."""
import json
from pathlib import Path

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
TIMEFRAMES_MS = {"5m": 300_000, "15m": 900_000}
DATA_DIR = Path("data/market_history")


def audit_file(path, interval_ms):
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                candle = {
                    "timestamp": int(row["timestamp"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                raise ValueError(f"{path}:{line_number}: malformed candle: {error}") from error
            values = [candle[k] for k in ("open", "high", "low", "close", "volume")]
            if not all(map(lambda value: value == value and abs(value) != float("inf"), values)):
                raise ValueError(f"{path}:{line_number}: non-finite OHLCV value")
            if candle["timestamp"] < 0 or any(candle[k] <= 0 for k in ("open", "high", "low", "close")) or candle["volume"] < 0:
                raise ValueError(f"{path}:{line_number}: invalid timestamp, price, or volume")
            if candle["high"] < max(candle["open"], candle["close"], candle["low"]):
                raise ValueError(f"{path}:{line_number}: high is below another OHLC value")
            if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
                raise ValueError(f"{path}:{line_number}: low is above another OHLC value")
            rows.append(candle)

    timestamps = [row["timestamp"] for row in rows]
    if timestamps != sorted(timestamps):
        raise ValueError(f"{path}: timestamps are not sorted")
    if len(timestamps) != len(set(timestamps)):
        raise ValueError(f"{path}: duplicate timestamps")
    gaps = [
        (timestamps[i] - timestamps[i - 1]) // interval_ms - 1
        for i in range(1, len(timestamps))
        if timestamps[i] - timestamps[i - 1] > interval_ms
    ]
    return {
        "candles": len(rows),
        "first_timestamp": timestamps[0] if rows else None,
        "last_timestamp": timestamps[-1] if rows else None,
        "gap_count": len(gaps),
        "missing_intervals_estimate": sum(gaps),
    }


def audit_archive(data_dir=DATA_DIR):
    report = {}
    errors = []
    for symbol in SYMBOLS:
        safe = symbol.replace("/", "_").replace(":", "_")
        for timeframe, interval in TIMEFRAMES_MS.items():
            path = Path(data_dir) / f"{safe}_{timeframe}.jsonl"
            key = f"{symbol} {timeframe}"
            if not path.exists():
                errors.append(f"{key}: archive file missing")
                continue
            try:
                result = audit_file(path, interval)
                if result["candles"] == 0:
                    errors.append(f"{key}: archive is empty")
                report[key] = result
            except (OSError, ValueError) as error:
                errors.append(f"{key}: {error}")
    return report, errors


def main():
    report, errors = audit_archive()
    print(json.dumps({"archives": report, "errors": errors}, indent=2))
    if errors:
        raise SystemExit("Market history audit failed")
    print("Market history audit passed; gaps are reported for review, not silently ignored.")


if __name__ == "__main__":
    main()
