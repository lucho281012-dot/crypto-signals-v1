
import json
import os
import time
import hashlib
import urllib.request
from urllib.parse import urlencode
from datetime import datetime, timezone


BASE_URL = "https://data-api.binance.vision/api/v3/klines"
SNAPSHOT_FILE = "historical_snapshot.json"


def load_snapshot(days=365):
    with open(
        SNAPSHOT_FILE,
        "r",
        encoding="utf-8"
    ) as file:
        snapshot = json.load(file)

    if snapshot.get("status") != "success":
        raise ValueError("Invalid historical snapshot")

    if snapshot.get("symbol") != "BTCUSDT":
        raise ValueError("Snapshot symbol mismatch")

    if snapshot.get("timeframe") != "H1":
        raise ValueError("Snapshot timeframe mismatch")

    candles = snapshot.get("candles")

    if not isinstance(candles, list):
        raise ValueError("Invalid snapshot candles")

    if len(candles) < 200:
        raise ValueError("Not enough snapshot candles")

    if len(candles) != snapshot.get("candles_count"):
        raise ValueError("Snapshot candle count mismatch")

    serialized = json.dumps(
        candles,
        separators=(",", ":")
    )

    calculated_hash = hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()

    saved_hash = snapshot.get("sha256")

    if not saved_hash or calculated_hash != saved_hash:
        raise ValueError(
            "Historical snapshot SHA-256 verification failed"
        )

    if days < snapshot.get("history_days", 365):
        candles = candles[-days * 24:]

    return candles


def download_historical_candles(days=180):
    if os.path.exists(SNAPSHOT_FILE):
        return load_snapshot(days)

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days * 24 * 60 * 60 * 1000

    all_candles = []

    while start_ms < now_ms:
        params = {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "limit": 1000,
            "startTime": start_ms
        }

        url = BASE_URL + "?" + urlencode(params)

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "BTCUSD-Signals-Bot/1.0"}
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.loads(
                response.read().decode("utf-8")
            )

        if not batch:
            break

        all_candles.extend(batch)

        last_open = int(batch[-1][0])
        next_start = last_open + 60 * 60 * 1000

        if next_start <= start_ms:
            raise ValueError(
                "Historical data pagination error"
            )

        start_ms = next_start

        if len(batch) < 1000:
            break

        time.sleep(0.2)

    current_time = int(time.time() * 1000)

    unique = {
        int(candle[0]): candle
        for candle in all_candles
        if int(candle[6]) < current_time
    }

    candles = [
        unique[key]
        for key in sorted(unique)
    ]

    if len(candles) < 200:
        raise ValueError("Not enough historical candles")

    return candles


if __name__ == "__main__":
    candles = download_historical_candles()

    print(json.dumps({
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candles_received": len(candles),
        "first_candle_utc": datetime.fromtimestamp(
            candles[0][0] / 1000,
            timezone.utc
        ).isoformat(),
        "last_candle_utc": datetime.fromtimestamp(
            candles[-1][0] / 1000,
            timezone.utc
        ).isoformat()
    }, indent=2))
