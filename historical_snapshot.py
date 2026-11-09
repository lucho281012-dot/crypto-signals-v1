
import json
import hashlib
from datetime import datetime, timezone

from historical_data import download_historical_candles


SNAPSHOT_FILE = "historical_snapshot.json"
HISTORY_DAYS = 365

# Vela seleccionada en MT5:
# 9 de noviembre de 2026, 19:00 hora del servidor.
# Equivalencia candidata: 17:00 UTC.
TARGET_UTC = datetime(
    2026, 11, 9, 17, 0,
    tzinfo=timezone.utc
)

MT5_CANDLE = {
    "open": 74695.50,
    "high": 74802.50,
    "low": 74303.50,
    "close": 74557.50
}


def compare_candles(candles):
    target_ms = int(TARGET_UTC.timestamp() * 1000)

    binance_candle = next(
        (
            candle for candle in candles
            if int(candle[0]) == target_ms
        ),
        None
    )

    if binance_candle is None:
        raise ValueError(
            "Target Binance candle not found: "
            + TARGET_UTC.isoformat()
        )

    binance_values = {
        "open": float(binance_candle[1]),
        "high": float(binance_candle[2]),
        "low": float(binance_candle[3]),
        "close": float(binance_candle[4])
    }

    differences = {
        key: round(
            MT5_CANDLE[key] - binance_values[key],
            2
        )
        for key in MT5_CANDLE
    }

    comparison = {
        "status": "success",
        "target_utc": TARGET_UTC.isoformat(),
        "mt5": MT5_CANDLE,
        "binance": binance_values,
        "difference_mt5_minus_binance": differences
    }

    print("\nMT5 VS BINANCE CANDLE COMPARISON")
    print(json.dumps(comparison, indent=2))

    return comparison


def main():
    candles = download_historical_candles(
        days=HISTORY_DAYS
    )

    if len(candles) < 1000:
        raise ValueError(
            "Not enough historical candles for snapshot"
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
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candles": len(candles),
        "first_candle_utc": snapshot["first_candle_utc"],
        "last_candle_utc": snapshot["last_candle_utc"],
        "sha256": checksum
    }, indent=2))

    compare_candles(candles)


if __name__ == "__main__":
    main()
