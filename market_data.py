import ccxt

exchange = ccxt.kraken({
    "enableRateLimit": True
})

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT"
]


def _format_candles(raw_candles):
    return [
        {
            "timestamp": candle[0],
            "open": candle[1],
            "high": candle[2],
            "low": candle[3],
            "close": candle[4],
            "volume": candle[5]
        }
        for candle in raw_candles
    ]


def get_market_price(symbol):
    exchange.load_markets()

    if symbol not in exchange.markets:
        raise ValueError(f"Par no disponible en Kraken: {symbol}")

    ticker = exchange.fetch_ticker(symbol)
    return ticker["last"]


def get_candles(symbol, timeframe="5m", limit=250):
    candles = exchange.fetch_ohlcv(
        symbol,
        timeframe=timeframe,
        limit=limit
    )
    return _format_candles(candles)


def get_candles_since(symbol, since, timeframe="5m"):
    """Recupera velas desde un timestamp (ms), usando paginación CCXT."""
    exchange.load_markets()

    if symbol not in exchange.markets:
        raise ValueError(f"Par no disponible en Kraken: {symbol}")

    candles = exchange.fetch_ohlcv(
        symbol,
        timeframe=timeframe,
        since=int(since),
        limit=720,
        params={"paginate": True}
    )

    # Kraken/CCXT puede incluir la vela del límite inicial.
    # Filtramos estrictamente después del último timestamp procesado.
    unique = {
        candle[0]: candle
        for candle in candles
        if candle[0] >= int(since)
    }
    return _format_candles([unique[key] for key in sorted(unique)])


def get_all_market_data():
    results = {}

    exchange.load_markets()

    for symbol in SYMBOLS:
        try:
            if symbol not in exchange.markets:
                print(f"Par no disponible: {symbol}")
                continue

            results[symbol] = {
                "price": get_market_price(symbol),
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
