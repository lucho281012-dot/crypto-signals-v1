import ccxt

exchange = ccxt.kraken({
    "enableRateLimit": True
})

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT"
]

# Kraken's Spot OHLC endpoint exposes at most its 720 most recent entries.
KRAKEN_OHLC_MAX_CANDLES = 720


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
    """Recupera velas recientes sin paginar más allá del límite de Kraken."""
    exchange.load_markets()

    if symbol not in exchange.markets:
        raise ValueError(f"Par no disponible en Kraken: {symbol}")

    since = int(since)
    timeframe_ms = int(exchange.parse_timeframe(timeframe) * 1000)
    if timeframe_ms <= 0:
        raise ValueError(f"Timeframe no válido: {timeframe}")

    expected_first_timestamp = (
        (since + timeframe_ms - 1) // timeframe_ms
    ) * timeframe_ms

    # Kraken solo conserva las 720 entradas OHLC más recientes. Rechazamos
    # huecos demasiado antiguos ANTES de llamar a la API: activar la
    # paginación de CCXT aquí puede generar muchas solicitudes inútiles.
    current_candle_start = (
        int(exchange.milliseconds()) // timeframe_ms
    ) * timeframe_ms
    oldest_recoverable_timestamp = (
        current_candle_start - (KRAKEN_OHLC_MAX_CANDLES - 1) * timeframe_ms
    )
    if expected_first_timestamp < oldest_recoverable_timestamp:
        raise RuntimeError(
            f"Rango fuera del histórico recuperable de Kraken para {symbol}. "
            f"Primera vela solicitada: {expected_first_timestamp}; "
            f"límite aproximado: {oldest_recoverable_timestamp}. "
            f"Kraken expone como máximo {KRAKEN_OHLC_MAX_CANDLES} velas "
            f"para el timeframe {timeframe}. Se conserva el cursor."
        )

    # Una sola petición: el endpoint Kraken OHLC tiene un máximo duro de
    # 720 entradas. No usar params={'paginate': True}, que puede disparar
    # llamadas adicionales cuando el cursor está muy atrás.
    candles = exchange.fetch_ohlcv(
        symbol,
        timeframe=timeframe,
        since=since,
        limit=KRAKEN_OHLC_MAX_CANDLES
    )

    unique = {
        int(candle[0]): candle
        for candle in candles
        if int(candle[0]) >= since
    }
    ordered = [unique[key] for key in sorted(unique)]

    if not ordered or int(ordered[0][0]) != expected_first_timestamp:
        raise RuntimeError(
            f"Kraken no devolvió la primera vela solicitada para {symbol}. "
            f"Esperada: {expected_first_timestamp}; "
            f"recibida: {int(ordered[0][0]) if ordered else 'ninguna'}. "
            "El rango puede contener un intervalo sin datos o haber "
            "quedado fuera del histórico disponible. Se conserva el cursor."
        )

    return _format_candles(ordered)


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
