
import json
import hashlib
from datetime import datetime, timezone, timedelta

from historical_data import download_historical_candles

SNAPSHOT_FILE = "historical_snapshot.json"
HISTORY_DAYS = 365

MT5_CANDLE = {
    "open": 74695.50,
    "high": 74802.50,
    "low": 74303.50,
    "close": 74557.50
}

TARGET_UTC = datetime(
    2026, 11, 9, 17, 0,
    tzinfo=timezone.utc
)


def compare_nearby_candles(candles):
    print("\nMT5 VS BINANCE - NEARBY CANDLES")

    candle_map = {
        int(candle[0]): candle
        for candle in candles
    }

    for hour_offset in [-1, 0, 1]:
        target = TARGET_UTC + timedelta(
            hours=hour_offset
        )

        target_ms = int(target.timestamp() * 1000)
        candle = candle_map.get(target_ms)

        print(f"\nBINANCE {target.isoformat()}")

        if candle is None:
            print(json.dumps({
                "status": "not_available",
                "reason": "Candle missing or not yet closed"
            }, indent=2))
            continue

        values = {
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4])
        }

        differences = {
            key: round(
                MT5_CANDLE[key] - values[key], 2
            )
            for key in MT5_CANDLE
        }

        print(json.dumps({
            "status": "success",
            "binance": values,
            "difference_mt5_minus_binance": differences
        }, indent=2))


def main():
    candles = download_historical_candles(
        days=HISTORY_DAYS
    )

    if len(candles) < 1000:
        raise ValueError(
            "Not enough historical candles"
        )

    first_time = int(candles[0][0])
    last_time = int(candles[-1][0])

    serialized = json.dumps(
        candles,
        separators=(",", ":")
    )

    checksum = hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()

    snapshot = {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "history_days": HISTORY_DAYS,
        "candles_count": len(candles),
        "first_candle_utc": datetime.fromtimestamp(
            first_time / 1000,
            timezone.utc
        ).isoformat(),
        "last_candle_utc": datetime.fromtimestamp(
            last_time / 1000,
            timezone.utc
        ).isoformat(),
        "sha256": checksum,
        "candles": candles
    }

    with open(
        SNAPSHOT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            snapshot,
            file,
            separators=(",", ":")
        )

    print(json.dumps({
        "status": "success",
        "file": SNAPSHOT_FILE,
        "candles": len(candles),
        "sha256": checksum
    }, indent=2))

    compare_nearby_candles(candles)


if __name__ == "__main__":
    main()
