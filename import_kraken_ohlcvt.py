"""Import selected Kraken OHLCVT CSV files into the research JSONL archive.

The source CSVs are headerless: timestamp_seconds,open,high,low,close,volume,trades.
This script only transforms local files; it performs no downloads or network calls.
"""
import argparse
import csv
import json
from pathlib import Path

from market_history_collector import TIMEFRAMES, archive_path, load_archive, validate_candle

SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
INTERVAL_FILES = {"5m": "5", "15m": "15"}


def import_csv(source: Path, symbol: str, timeframe: str, output_dir: Path) -> dict:
    if timeframe not in INTERVAL_FILES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    interval = TIMEFRAMES[timeframe]
    target = output_dir / f"{symbol.replace('/', '_')}_{timeframe}.jsonl"
    existing = load_archive(target, interval)
    before = len(existing)
    imported = 0
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for line_number, row in enumerate(reader, 1):
            if not row:
                continue
            if len(row) < 6:
                raise ValueError(f"{source}:{line_number}: expected at least 6 columns")
            try:
                seconds = float(row[0])
                if not seconds.is_integer():
                    raise ValueError("timestamp must be whole epoch seconds")
                candle = validate_candle({
                    "timestamp": int(seconds) * 1000,
                    "open": row[1], "high": row[2], "low": row[3],
                    "close": row[4], "volume": row[5],
                }, interval)
            except (TypeError, ValueError) as error:
                raise ValueError(f"{source}:{line_number}: {error}") from error
            existing[candle["timestamp"]] = candle
            imported += 1
    ordered = [existing[key] for key in sorted(existing)]
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for candle in ordered:
            handle.write(json.dumps(candle, separators=(",", ":")) + "\n")
    return {
        "symbol": symbol, "timeframe": timeframe, "source": str(source),
        "rows_read": imported, "new_timestamps": len(existing) - before,
        "total_rows": len(ordered),
        "first_timestamp": ordered[0]["timestamp"] if ordered else None,
        "last_timestamp": ordered[-1]["timestamp"] if ordered else None,
        "output": str(target),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="data/market_history")
    for symbol in SYMBOLS:
        key = symbol.split("/")[0].lower()
        for timeframe in INTERVAL_FILES:
            parser.add_argument(f"--{key}-{timeframe}", required=True,
                                help=f"Kraken OHLCVT CSV for {symbol} {timeframe}")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    results = []
    for symbol in SYMBOLS:
        key = symbol.split("/")[0].lower()
        for timeframe in INTERVAL_FILES:
            source = Path(getattr(args, f"{key}_{timeframe}"))
            results.append(import_csv(source, symbol, timeframe, output_dir))
    print(json.dumps({
        "mode": "local_historical_import_no_network_no_orders",
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()
