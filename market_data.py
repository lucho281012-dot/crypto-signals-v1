
import ccxt


exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {
        "defaultType": "spot"
    }
})

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT"
]


def get_market_price(symbol):
    ticker = exchange.fetch_ticker(symbol)
    return ticker["last"]


def get_candles(symbol, timeframe="5m", limit=250):
    candles = exchange.fetch_ohlcv(
        symbol,
        timeframe=timeframe,
        limit=limit
    )

    return [
        {
            "timestamp": candle[0],
            "open": candle[1],
            "high": candle[2],
            "low": candle[3],
            "close": candle[4],
            "volume": candle[5]
        }
        for candle in candles
    ]


def get_all_market_data():
    results = {}

    for symbol in SYMBOLS:
        try:
            results[symbol] = {
                "price": get_market_price(symbol),
                "candles_5m": get_candles(symbol, "5m"),
                "candles_15m": get_candles(symbol, "15m")
            }
        except Exception as error:
            print(f"Error consultando {symbol}: {error}")

    return results


if __name__ == "__main__":
    data = get_all_market_data()

    for symbol, info in data.items():
        print(
            symbol,
            "Precio:",
            info["price"],
            "Velas 5m:",
            len(info["candles_5m"])
        )
