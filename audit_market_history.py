"""Read-only temporal and cross-symbol audit for archived Kraken OHLCV JSONL."""
import argparse
import json
from pathlib import Path

from market_history_collector import SYMBOLS, TIMEFRAMES, validate_candle


def audit_file(path: Path, interval: int) -> dict:
    timestamps, errors, previous = [], [], None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    candle = validate_candle(json.loads(line), interval)
                    ts = candle["timestamp"]
                    if previous is not None and ts <= previous:
                        errors.append({"line": line_number, "error": "timestamps_not_strictly_increasing"})
                    previous = ts
                    timestamps.append(ts)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    errors.append({"line": line_number, "error": str(exc)})
    except FileNotFoundError:
        errors.append({"error": "file_not_found"})
    unique = sorted(set(timestamps))
    gaps = []
    for left, right in zip(unique, unique[1:]):
        delta = right - left
        if delta != interval:
            gaps.append({
                "after": left, "before": right,
                "missing_intervals_estimate": delta // interval - 1 if delta > interval and delta % interval == 0 else None,
                "misaligned_delta": delta % interval != 0,
            })
    return {
        "file": str(path), "rows_read": len(timestamps),
        "unique_timestamps": len(unique), "duplicate_rows": len(timestamps) - len(unique),
        "first_timestamp": unique[0] if unique else None,
        "last_timestamp": unique[-1] if unique else None,
        "gap_count": len(gaps), "first_gap": gaps[0] if gaps else None,
        "errors": errors[:20], "valid": not errors, "_timestamps": unique,
    }


def audit_dataset(root: Path) -> dict:
    reports = {}
    for symbol in SYMBOLS:
        for timeframe, interval in TIMEFRAMES.items():
            path = root / f"{symbol.replace('/', '_')}_{timeframe}.jsonl"
            reports[f"{symbol}:{timeframe}"] = audit_file(path, interval)

    cross_symbol = {}
    for timeframe in TIMEFRAMES:
        sets = {s: set(reports[f"{s}:{timeframe}"]["_timestamps"]) for s in SYMBOLS}
        present = {s: values for s, values in sets.items() if values}
        if present:
            common_start = max(min(v) for v in present.values())
            common_end = min(max(v) for v in present.values())
            shared = set.intersection(*present.values()) if len(present) == len(SYMBOLS) else set()
        else:
            common_start = common_end = None
            shared = set()
        cross_symbol[timeframe] = {
            "symbols_present": sorted(present),
            "common_overlap_start": common_start, "common_overlap_end": common_end,
            "overlap_exists": common_start is not None and common_end is not None and common_start <= common_end,
            "exact_shared_timestamps_count": len(shared),
            "note": "Symbols may omit intervals with no trades; gaps are reported, never filled.",
        }
    clean = {key: {k: v for k, v in value.items() if k != "_timestamps"} for key, value in reports.items()}
    return {
        "mode": "read_only_temporal_audit", "files": clean, "cross_symbol": cross_symbol,
        "valid": all(item["valid"] for item in reports.values()),
        "note": "Structural validity does not imply gap-free history or backtest readiness.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/market_history")
    args = parser.parse_args()
    report = audit_dataset(Path(args.data_dir))
    print(json.dumps(report, indent=2))
    if not report["valid"]:
        raise SystemExit("Temporal audit found structural errors")


if __name__ == "__main__":
    main()
