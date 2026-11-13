"""Guarded baseline reset for stale paper-trading candle checkpoints.

Default is read-only DRY-RUN. --apply creates a backup and updates only
last_processed_candle plus baseline metadata. It never opens/closes positions.
"""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from market_data import SYMBOLS, get_candles

EXPECTED_STATE_BLOB_SHA = "4510a2e382a6e354ce2131d8bed7ac24b567d8ae"
TIMEFRAME_MS = 5 * 60 * 1000


def git_blob_sha(raw):
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()


def utc_from_ms(value):
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def build_plan(state, raw, candles_by_symbol):
    actual_sha = git_blob_sha(raw)
    if actual_sha != EXPECTED_STATE_BLOB_SHA:
        raise ValueError(
            f"State changed: expected {EXPECTED_STATE_BLOB_SHA}, got {actual_sha}; "
            "stop and re-audit."
        )

    if state.get("positions") != {}:
        raise ValueError("Open positions detected; refusing to rebaseline.")
    if set(state.get("last_processed_candle", {})) != set(SYMBOLS):
        raise ValueError("Saved checkpoints do not exactly match configured symbols.")

    new_checkpoints = {}
    report = []
    for symbol in SYMBOLS:
        candles = candles_by_symbol.get(symbol)
        if not candles or len(candles) < 3:
            raise ValueError(f"{symbol}: insufficient 5m candle data.")
        timestamps = [int(c["timestamp"]) for c in candles]
        if timestamps != sorted(set(timestamps)):
            raise ValueError(f"{symbol}: candle timestamps are duplicated or unordered.")
        if any(ts % TIMEFRAME_MS != 0 for ts in timestamps):
            raise ValueError(f"{symbol}: candle timestamp is not aligned to 5m.")
        latest_closed = timestamps[-2]
        old = int(state["last_processed_candle"][symbol])
        if latest_closed <= old:
            raise ValueError(
                f"{symbol}: latest closed candle {latest_closed} is not newer "
                f"than saved checkpoint {old}."
            )
        new_checkpoints[symbol] = str(latest_closed)
        report.append({
            "symbol": symbol,
            "old_checkpoint": old,
            "old_checkpoint_utc": utc_from_ms(old),
            "new_checkpoint": latest_closed,
            "new_checkpoint_utc": utc_from_ms(latest_closed),
            "skipped_intervals": max(0, (latest_closed - old) // TIMEFRAME_MS - 1),
            "latest_closed_candle_close": candles[-2]["close"],
        })

    updated = dict(state)
    updated["last_processed_candle"] = new_checkpoints
    updated["baseline_metadata"] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "skip_stale_history_no_retroactive_signals",
        "timeframe": "5m",
        "symbols": list(SYMBOLS),
        "note": "Historical gap intentionally skipped; no trades were simulated for skipped candles."
    }
    return updated, report


def atomic_write(path, state):
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path", default="data/paper_state.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    path = Path(args.state_path)
    raw = path.read_bytes()
    state = json.loads(raw.decode("utf-8"))

    candles = {
        symbol: get_candles(symbol, timeframe="5m", limit=250)
        for symbol in SYMBOLS
    }
    updated, report = build_plan(state, raw, candles)

    print(json.dumps({
        "mode": "APPLY" if args.apply else "DRY-RUN",
        "state_sha_before": git_blob_sha(raw),
        "open_positions_before": len(state.get("positions", {})),
        "closed_trades_preserved": len(state.get("history", [])),
        "cash_usdt_preserved": state.get("cash_usdt"),
        "checkpoints": report,
        "positions_created": 0,
        "positions_closed": 0,
        "historical_signals_created": 0,
    }, indent=2))

    if not args.apply:
        print("DRY-RUN ONLY: no files changed. Review timestamps before applying.")
        return

    backup = path.with_name(path.name + ".pre_rebaseline.bak")
    if backup.exists():
        raise FileExistsError(f"Backup already exists: {backup}; refusing overwrite.")
    shutil.copy2(path, backup)
    atomic_write(path, updated)
    print(f"APPLIED. Original state backup: {backup}")
    print(f"state_sha_after: {git_blob_sha(path.read_bytes())}")


if __name__ == "__main__":
    main()
