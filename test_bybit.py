
import requests
from datetime import datetime, timezone

BASE_URL = "https://api.bybit.com/v5/market/kline"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAMES = ["5", "15"]


def test_market_data(symbol, interval):
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "limit": 3
    }

    response = requests.get(BASE_URL, params=params, timeout=20)
    response.raise_for_status()

    data = response.json()

    if data.get("retCode") != 0:
        raise RuntimeError(
            f"Error de Bybit: {data.get('retMsg')}"
        )

    candles = data["result"]["list"]

    if not candles:
        raise RuntimeError("Bybit no devolvió velas")

    # Bybit devuelve las velas en orden inverso.
    candles = sorted(candles, key=lambda x: int(x[0]))

    print(f"\n{symbol} - {interval} minutos")
    print(f"Velas recibidas: {len(candles)}")

    for candle in candles:
        timestamp = datetime.fromtimestamp(
            int(candle[0]) / 1000,
            timezone.utc
        )

        print(
            f"{timestamp:%Y-%m-%d %H:%M UTC} | "
            f"O: {candle[1]} | "
            f"H: {candle[2]} | "
            f"L: {candle[3]} | "
            f"C: {candle[4]} | "
            f"V: {candle[5]}"
        )


def main():
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            test_market_data(symbol, timeframe)

    print("\nPRUEBA COMPLETADA CORRECTAMENTE")


if __name__ == "__main__":
    main()

