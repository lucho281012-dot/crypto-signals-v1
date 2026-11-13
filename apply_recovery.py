"""Guarded recovery of two previously reconstructed paper positions.

Default mode is DRY-RUN. No state is changed unless --apply is supplied.
The script is intentionally tied to the audited state blob and exact positions.
"""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

STATE_PATH = Path("data/paper_state.json")
EXPECTED_STATE_BLOB_SHA = "6f82e0c0df510a6316acc492c201217380435c63"
FEE_RATE = 0.001
RECOVERY_SOURCE = "Kraken public Trades; rebuilt 5m bars; paper_bot.py stop-first rules"

EVENTS = {
    "ETH/USDT": {
        "event_time": "2026-11-05T04:00:00+00:00",
        "exit_price": 2424.12,
        "reason": "stop_loss",
        "expected_entry": 2428.45,
        "expected_quantity": 0.0019540261258229456,
    },
    "SOL/USDT": {
        "event_time": "2026-11-05T03:15:00+00:00",
        "exit_price": 96.59,
        "reason": "take_profit",
        "expected_entry": 96.06,
        "expected_quantity": 0.0024699431320293194,
    },
}


def git_blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def close_record(symbol, position, event):
    quantity = float(position["quantity"])
    entry_price = float(position["entry_price"])
    entry_fee = float(position["entry_fee"])
    exit_price = float(event["exit_price"])
    proceeds = quantity * exit_price
    exit_fee = proceeds * FEE_RATE
    net_pnl = proceeds - exit_fee - quantity * entry_price - entry_fee

    return {
        **position,
        "symbol": symbol,
        "exit_price": exit_price,
        "exit_fee": exit_fee,
        "net_pnl": net_pnl,
        "reason": event["reason"],
        # This is the historical simulated trigger time, not the recovery run time.
        "closed_at": event["event_time"],
        "event_time": event["event_time"],
        "recovered": True,
        "recovery_source": RECOVERY_SOURCE,
    }


def build_plan(state, raw):
    actual_sha = git_blob_sha(raw)
    if actual_sha != EXPECTED_STATE_BLOB_SHA:
        raise ValueError(
            f"State changed: expected blob {EXPECTED_STATE_BLOB_SHA}, got {actual_sha}. "
            "Stop and re-audit; do not overwrite a newer state."
        )

    if set(state.get("positions", {})) != set(EVENTS):
        raise ValueError("Open positions do not exactly match the two audited recovery events.")

    existing_recoveries = {
        trade.get("symbol") for trade in state.get("history", [])
        if trade.get("recovered") is True
    }
    if existing_recoveries.intersection(EVENTS):
        raise ValueError("A recovery record already exists; refusing a duplicate application.")

    new_history = list(state.get("history", []))
    total_net_pnl = 0.0
    cash_addition = 0.0
    records = []

    for symbol, event in EVENTS.items():
        position = state["positions"][symbol]
        if abs(float(position["entry_price"]) - event["expected_entry"]) > 1e-10:
            raise ValueError(f"{symbol}: entry price differs from audited position.")
        if abs(float(position["quantity"]) - event["expected_quantity"]) > 1e-14:
            raise ValueError(f"{symbol}: quantity differs from audited position.")

        record = close_record(symbol, position, event)
        records.append(record)
        new_history.append(record)
        total_net_pnl += record["net_pnl"]
        cash_addition += record["quantity"] * record["exit_price"] - record["exit_fee"]

    updated = dict(state)
    updated["cash_usdt"] = float(state["cash_usdt"]) + cash_addition
    updated["positions"] = {}
    updated["history"] = new_history

    return {
        "updated_state": updated,
        "records": records,
        "cash_after": updated["cash_usdt"],
        "recovered_net_pnl": total_net_pnl,
        "realized_pnl_after": sum(float(t["net_pnl"]) for t in new_history),
        "checkpoint_unchanged": True,
    }


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(content, handle, indent=2)
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
    parser.add_argument("--apply", action="store_true", help="write the guarded recovery to paper_state.json")
    args = parser.parse_args()

    raw = STATE_PATH.read_bytes()
    state = json.loads(raw.decode("utf-8"))
    plan = build_plan(state, raw)

    summary = {
        "mode": "APPLY" if args.apply else "DRY-RUN",
        "records": [
            {
                "symbol": item["symbol"],
                "event_time": item["event_time"],
                "exit_price": item["exit_price"],
                "exit_fee": item["exit_fee"],
                "net_pnl": item["net_pnl"],
                "reason": item["reason"],
            }
            for item in plan["records"]
        ],
        "cash_after": plan["cash_after"],
        "recovered_net_pnl": plan["recovered_net_pnl"],
        "realized_pnl_after": plan["realized_pnl_after"],
        "checkpoint_unchanged": plan["checkpoint_unchanged"],
    }

    if not args.apply:
        print(json.dumps(summary, indent=2))
        print("DRY-RUN ONLY: no files changed. Use --apply only after reviewing this exact plan.")
        return

    backup = STATE_PATH.with_name(STATE_PATH.name + ".pre_recovery.bak")
    if backup.exists():
        raise FileExistsError(f"Backup already exists: {backup}; refusing to overwrite it.")
    shutil.copy2(STATE_PATH, backup)
    atomic_write(STATE_PATH, plan["updated_state"])
    print(json.dumps(summary, indent=2))
    print(f"Recovery applied. Original state backup: {backup}")


if __name__ == "__main__":
    main()
