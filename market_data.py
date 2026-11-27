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

    if not ordered:
        raise RuntimeError(
            f"Kraken no devolvió velas para {symbol} desde {since}. "
            "Se conserva el cursor."
        )

    # Kraken puede omitir intervalos sin operaciones, incluso la vela usada
    # como cursor. La validación de la semilla se hace en paper_bot.py, donde
    # también se conoce si existe last_processed_close persistido.
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


def validate_entry_round(market_data, symbols=None):
    """Valida que una ronda de nuevas entradas use velas cerradas sincronizadas.

    Devuelve metadatos por símbolo. Lanza ValueError ante datos ausentes,
    desordenados, duplicados, desalineados o con una vela de entrada no
    inmediatamente posterior a la vela de señal.
    """
    symbols = list(SYMBOLS if symbols is None else symbols)
    if not symbols:
        raise ValueError("La ronda no contiene símbolos.")

    missing = [symbol for symbol in symbols if symbol not in market_data]
    if missing:
        raise ValueError(
            "Ronda incompleta; faltan símbolos: " + ", ".join(missing)
        )

    validated = {}
    signal_timestamps = set()

    for symbol in symbols:
        data = market_data[symbol]
        candles_5m = data.get("candles_5m") or []
        candles_15m = data.get("candles_15m") or []

        if len(candles_5m) < 3:
            raise ValueError(f"{symbol}: se requieren al menos 3 velas 5m.")
        if len(candles_15m) < 2:
            raise ValueError(f"{symbol}: faltan velas 15m.")

        for timeframe, candles, interval in (
            ("5m", candles_5m, 300000),
            ("15m", candles_15m, 900000),
        ):
            timestamps = []
            for candle in candles:
                try:
                    timestamp = int(candle["timestamp"])
                except (KeyError, TypeError, ValueError):
                    raise ValueError(
                        f"{symbol}: timestamp inválido en {timeframe}."
                    )
                if timestamp % interval:
                    raise ValueError(
                        f"{symbol}: timestamp desalineado en {timeframe}."
                    )
                timestamps.append(timestamp)

            if any(
                current <= previous
                for previous, current in zip(timestamps, timestamps[1:])
            ):
                raise ValueError(
                    f"{symbol}: velas {timeframe} desordenadas o duplicadas."
                )

        signal_candle = candles_5m[-2]
        entry_candle = candles_5m[-1]
        signal_timestamp = int(signal_candle["timestamp"])
        entry_timestamp = int(entry_candle["timestamp"])

        if entry_timestamp != signal_timestamp + 300000:
            raise ValueError(
                f"{symbol}: no existe la vela 5m inmediatamente posterior "
                "a la señal; no se puede simular una entrada segura."
            )

        # La vela 15m debe haber cerrado antes o exactamente al cierre
        # de la vela 5m que genera la señal. No aceptamos una tendencia vieja.
        signal_close_time = signal_timestamp + 300000
        expected_15m_timestamp = (
            (signal_close_time - 900000) // 900000
        ) * 900000
        latest_closed_15m = int(candles_15m[-2]["timestamp"])
        expected_open_15m_timestamp = (
            signal_close_time // 900000
        ) * 900000
        latest_open_15m = int(candles_15m[-1]["timestamp"])
        if latest_closed_15m != expected_15m_timestamp:
            raise ValueError(
                f"{symbol}: la última vela 15m cerrada no corresponde "
                "al instante de evaluación."
            )
        if latest_open_15m != expected_open_15m_timestamp:
            raise ValueError(
                f"{symbol}: falta la vela 15m actual correspondiente "
                "al instante de evaluación."
            )

        signal_timestamps.add(signal_timestamp)
        validated[symbol] = {
            "signal_timestamp": signal_timestamp,
            "entry_timestamp": entry_timestamp,
            "entry_price": float(entry_candle["open"]),
            "signal_close": float(signal_candle["close"]),
        }

    if len(signal_timestamps) != 1:
        raise ValueError(
            "Ronda no sincronizada: las últimas velas 5m cerradas "
            "no comparten el mismo timestamp."
        )

    return validated


if __name__ == "__main__":
    data = get_all_market_data()
    print("Activos recibidos:", list(data.keys()))
