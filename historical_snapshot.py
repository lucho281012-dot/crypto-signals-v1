
import json
import hashlib
from datetime import datetime, timezone

from historical_data import download_historical_candles


SNAPSHOT_FILE = "historical_snapshot.json"
HISTORY_DAYS = 365


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


if __name__ == "__main__":
    main()
