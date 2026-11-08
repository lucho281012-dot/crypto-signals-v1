
import json
import urllib.request
import time
from datetime import datetime, timezone



URL = (
    "https://data-api.binance.vision/api/v3/klines"
    "?symbol=BTCUSDT&interval=1h&limit=1000"
)



def download_candles():
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "BTCUSD-Signals-Bot/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        candles = json.loads(response.read().decode("utf-8"))

    now_ms = int(time.time() * 1000)

    # Utilizar solamente velas H1 completamente cerradas
    closed = [
        candle for candle in candles
        if int(candle[6]) < now_ms
    ]

    if len(closed) < 51:
        raise ValueError("Insufficient closed candles")

    return closed


def ema(values, period=50):
    multiplier = 2 / (period + 1)
    result = values[0]

    for value in values[1:]:
        result = (value - result) * multiplier + result

    return result


def rsi(values, period=14):
    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    return 100 - (100 / (1 + avg_gain / avg_loss))


def atr(candles, period=14):
    ranges = []

    for i in range(1, len(candles)):
        high = float(candles[i][2])
        low = float(candles[i][3])
        previous_close = float(candles[i - 1][4])

        ranges.append(max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        ))

    result = sum(ranges[:period]) / period

    for value in ranges[period:]:
        result = (
            result * (period - 1) + value
        ) / period

    return result


def main():
    candles = download_candles()
    closes = [float(candle[4]) for candle in candles]

    last = candles[-1]

    result = {
        "source": "Binance Public Market Data",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candle_open_utc": datetime.fromtimestamp(
            last[0] / 1000,
            timezone.utc
        ).isoformat(),
        "close": closes[-1],
        "ema_50": ema(closes, 50),
        "rsi_14": rsi(closes, 14),
        "atr_14": atr(candles, 14),
        "candles_received": len(candles),
        "status": "success"
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({
            "status": "error",
            "message": str(error)
        }, indent=2))
