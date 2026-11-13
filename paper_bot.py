import math
import time

from market_data import SYMBOLS, get_all_market_data
from signal_engine import analyze_spot
from paper_trading import (
    load_state,
    save_state,
    open_position,
    close_position,
    get_status
)

INTERVAL_MS = {"5m": 5 * 60 * 1000, "15m": 15 * 60 * 1000}
MIN_CANDLES = 200
MAX_5M_AGE_MS = 15 * 60 * 1000
MAX_15M_AGE_MS = 30 * 60 * 1000
MAX_FUTURE_SKEW_MS = 60 * 1000
MAX_QUOTE_AGE_MS = 2 * 60 * 1000
MAX_ENTRY_DRIFT_PCT = 0.005


def _finite_number(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Campo no numérico: {field}")
    if not math.isfinite(number):
        raise ValueError(f"Campo no finito: {field}")
    return number


def _validate_candles(symbol, candles, timeframe, now_ms):
    interval = INTERVAL_MS[timeframe]
    max_age = MAX_5M_AGE_MS if timeframe == "5m" else MAX_15M_AGE_MS
    if not isinstance(candles, list) or len(candles) < MIN_CANDLES:
        raise ValueError(f"{symbol}: historial insuficiente en {timeframe}")

    timestamps = []
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict):
            raise ValueError(f"{symbol}: vela inválida en {timeframe}")
        timestamp = candle.get("timestamp")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise ValueError(f"{symbol}: timestamp inválido en {timeframe}")
        if not math.isfinite(float(timestamp)) or int(timestamp) != timestamp:
            raise ValueError(f"{symbol}: timestamp inválido en {timeframe}")
        timestamp = int(timestamp)
        if timestamp % interval:
            raise ValueError(f"{symbol}: vela desalineada en {timeframe}")
        if timestamps and timestamp <= timestamps[-1]:
            raise ValueError(f"{symbol}: timestamps no crecientes en {timeframe}")
        timestamps.append(timestamp)

        values = {
            key: _finite_number(candle.get(key), f"{symbol}.{timeframe}.{key}")
            for key in ("open", "high", "low", "close", "volume")
        }
        if min(values["open"], values["high"], values["low"], values["close"]) <= 0:
            raise ValueError(f"{symbol}: precio OHLC no positivo en {timeframe}")
        if values["volume"] < 0:
            raise ValueError(f"{symbol}: volumen negativo en {timeframe}")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError(f"{symbol}: máximo OHLC inconsistente en {timeframe}")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError(f"{symbol}: mínimo OHLC inconsistente en {timeframe}")

    last_closed_timestamp = timestamps[-2]
    age = now_ms - last_closed_timestamp
    if age < -MAX_FUTURE_SKEW_MS or age > max_age:
        raise ValueError(f"{symbol}: última vela cerrada desactualizada en {timeframe}")


def validate_market_data(market_data, now_ms):
    if not isinstance(market_data, dict):
        raise ValueError("Respuesta de mercado inválida")
    missing = sorted(set(SYMBOLS) - set(market_data))
    if missing:
        raise ValueError(f"Faltan activos requeridos: {', '.join(missing)}")

    for symbol in SYMBOLS:
        data = market_data[symbol]
        if not isinstance(data, dict):
            raise ValueError(f"{symbol}: datos inválidos")
        _validate_candles(symbol, data.get("candles_5m"), "5m", now_ms)
        _validate_candles(symbol, data.get("candles_15m"), "15m", now_ms)

        price = _finite_number(data.get("price"), f"{symbol}.price")
        quote_timestamp = data.get("price_timestamp")
        if price <= 0:
            raise ValueError(f"{symbol}: cotización no positiva")
        if isinstance(quote_timestamp, bool) or not isinstance(quote_timestamp, (int, float)):
            raise ValueError(f"{symbol}: timestamp de cotización inválido")
        if not math.isfinite(float(quote_timestamp)) or int(quote_timestamp) != quote_timestamp:
            raise ValueError(f"{symbol}: timestamp de cotización inválido")
        quote_age = now_ms - int(quote_timestamp)
        if quote_age < -MAX_FUTURE_SKEW_MS or quote_age > MAX_QUOTE_AGE_MS:
            raise ValueError(f"{symbol}: cotización desactualizada")


def run_bot(now_ms=None):
    # Validamos el conjunto completo antes de modificar el estado.
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    market_data = get_all_market_data()
    validate_market_data(market_data, now_ms)

    state = load_state()
    state.setdefault("last_processed_candle", {})

    for symbol in SYMBOLS:
        data = market_data[symbol]
        candles = data["candles_5m"]
        candle = candles[-2]
        candle_id = str(candle["timestamp"])

        if state["last_processed_candle"].get(symbol) == candle_id:
            continue

        position = state["positions"].get(symbol)

        if position:
            stop = position["stop_price"]
            target = position.get("target_price")

            if candle["low"] <= stop:
                exit_price = min(candle["open"], stop)
                success, message = close_position(
                    state, symbol, exit_price, "stop_loss", persist=False
                )
                print(symbol, "STOP LOSS" if success else message)

            elif target and candle["high"] >= target:
                exit_price = max(candle["open"], target)
                success, message = close_position(
                    state, symbol, exit_price, "take_profit", persist=False
                )
                print(symbol, "TAKE PROFIT" if success else message)

        else:
            signal = analyze_spot(candles, data["candles_15m"])
            if signal and signal["side"] == "BUY":
                signal_close = _finite_number(candle["close"], f"{symbol}.signal_close")
                entry_price = _finite_number(data["price"], f"{symbol}.price")
                drift = abs(entry_price - signal_close) / signal_close

                # No perseguimos una señal si el precio ya se alejó demasiado.
                if drift <= MAX_ENTRY_DRIFT_PCT:
                    atr = _finite_number(signal["atr"], f"{symbol}.atr")
                    if atr > 0:
                        stop_price = entry_price - (1.2 * atr)
                        target_price = entry_price + (2 * (entry_price - stop_price))
                        success, message = open_position(
                            state, symbol, entry_price, stop_price, persist=False
                        )
                        if success:
                            state["positions"][symbol]["target_price"] = target_price
                        print(message)
                else:
                    print(symbol, "Señal omitida: precio se alejó más de 0.5%")

        # Posición/historial y checkpoint se persisten en una sola escritura.
        state["last_processed_candle"][symbol] = candle_id
        save_state(state)

    print("Estado del simulador:")
    print(get_status(state))


if __name__ == "__main__":
    run_bot()
