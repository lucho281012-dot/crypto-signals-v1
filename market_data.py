import ccxt

exchange = ccxt.kraken({
    "enableRateLimit": True
})

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT"
]


def get_market_quote(symbol):
    exchange.load_markets()
    if symbol not in exchange.markets:
        raise ValueError(f"Par no disponible en Kraken: {symbol}")
    ticker = exchange.fetch_ticker(symbol)
    return ticker["last"], ticker.get("timestamp")


def get_market_price(symbol):
    price, _ = get_market_quote(symbol)
    return price


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
    exchange.load_markets()

    for symbol in SYMBOLS:
        try:
            if symbol not in exchange.markets:
                print(f"Par no disponible: {symbol}")
                continue

            price, price_timestamp = get_market_quote(symbol)
            results[symbol] = {
                "price": price,
                "price_timestamp": price_timestamp,
                "candles_5m": get_candles(symbol, "5m"),
                "candles_15m": get_candles(symbol, "15m")
            }
            print(f"Datos recibidos correctamente: {symbol}")

        except Exception as error:
            print(f"Error consultando {symbol}: {error}")

    return results


if __name__ == "__main__":
    data = get_all_market_data()
    print("Activos recibidos:", list(data.keys()))
