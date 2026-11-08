
import json
import time
import urllib.request
from urllib.parse import urlencode
from datetime import datetime, timezone


BASE_URL = "https://data-api.binance.vision/api/v3/klines"


def download_historical_candles(days=180):
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
            batch = json.loads(response.read().decode("utf-8"))

        if not batch:
            break

        all_candles.extend(batch)

        last_open = int(batch[-1][0])
        next_start = last_open + 60 * 60 * 1000

        if next_start <= start_ms:
            raise ValueError("Historical data pagination error")

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
