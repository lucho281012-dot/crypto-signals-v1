from market_data import get_all_market_data, get_candles_since
from signal_engine import analyze_spot
from paper_trading import (
    load_state,
    save_state,
    open_position,
    close_position,
    get_status
)


def process_position_exit(state, symbol, candle):
    """Aplica stop/objetivo a una posición usando una vela cerrada."""
    position = state["positions"].get(symbol)
    if not position:
        return None

    stop = position["stop_price"]
    target = position.get("target_price")

    # Si ambos niveles aparecen dentro de la misma vela, stop-loss tiene prioridad.
    if candle["low"] <= stop:
        exit_price = min(candle["open"], stop)
        close_position(state, symbol, exit_price, "stop_loss")
        print(symbol, "STOP LOSS")
        return "stop_loss"

    if target and candle["high"] >= target:
        exit_price = max(candle["open"], target)
        close_position(state, symbol, exit_price, "take_profit")
        print(symbol, "TAKE PROFIT")
        return "take_profit"

    return None


def get_pending_candles(symbol, last_processed, latest_closed, last_processed_close=None):
    """Recupera velas cerradas y reconstruye intervalos sin operaciones."""
    if last_processed is None:
        return [latest_closed]

    last_timestamp = int(last_processed)
    latest_timestamp = int(latest_closed["timestamp"])
    interval_ms = 300000

    if last_timestamp % interval_ms != 0 or latest_timestamp % interval_ms != 0:
        raise RuntimeError(
            f"Cursor o vela fuera de alineación de 5 minutos para {symbol}."
        )

    recovered = get_candles_since(symbol, last_timestamp, timeframe="5m")
    unique = {
        int(candle["timestamp"]): candle
        for candle in recovered
        if last_timestamp <= int(candle["timestamp"]) <= latest_timestamp
    }
    seed = unique.get(last_timestamp)
    if seed is None and last_processed_close is None:
        raise RuntimeError(
            f"Recuperación incompleta para {symbol}: no se pudo recuperar "
            "la vela usada como cursor ni existe un cierre persistido."
        )
    if latest_timestamp not in unique:
        raise RuntimeError(
            f"Recuperación incompleta para {symbol}: no se recibió "
            "la última vela cerrada."
        )

    pending = []
    previous_close = float(
        seed["close"] if seed is not None else last_processed_close
    )
    expected_timestamp = last_timestamp + interval_ms

    while expected_timestamp <= latest_timestamp:
        candle = unique.get(expected_timestamp)
        if candle is None:
            candle = {
                "timestamp": expected_timestamp,
                "open": previous_close,
                "high": previous_close,
                "low": previous_close,
                "close": previous_close,
                "volume": 0.0,
            }
        else:
            previous_close = float(candle["close"])
        pending.append(candle)
        expected_timestamp += interval_ms

    if not pending or int(pending[-1]["timestamp"]) != latest_timestamp:
        raise RuntimeError(
            f"Recuperación incompleta para {symbol}: no se pudo reconstruir "
            "hasta la última vela cerrada."
        )
    return pending


def open_signal_position(state, symbol, data):
    signal = analyze_spot(data["candles_5m"], data["candles_15m"])
    if not signal or signal["side"] != "BUY":
        return

    candles = data["candles_5m"]
    entry_price = float(candles[-1]["open"])
    stop_price = entry_price - (1.2 * signal["atr"])
    target_price = entry_price + (2 * (entry_price - stop_price))

    diagnostic = dict(signal["signal_diagnostic"])
    diagnostic["symbol"] = symbol
    diagnostic["execution"] = {
        "timeframe": "5m",
        "entry_candle_timestamp": int(candles[-1]["timestamp"]),
        "entry_open": entry_price,
        "simulated_entry_price": entry_price,
    }

    success, message = open_position(
        state,
        symbol,
        entry_price,
        stop_price,
        signal_diagnostic=diagnostic,
    )
    if success:
        state["positions"][symbol]["target_price"] = target_price
        # A diagnostic is retained even if the risk/capital guard blocks entry.
        state.setdefault("signal_diagnostics", []).append({
            **diagnostic,
            "entry_blocked_reason": None,
        })
        del state["signal_diagnostics"][:-10000]
        save_state(state)
    else:
        state.setdefault("signal_diagnostics", []).append({
            **diagnostic,
            "entry_blocked_reason": message,
        })
        del state["signal_diagnostics"][:-10000]
        save_state(state)

    print(message)


def run_bot():
    state = load_state()
    state.setdefault("last_processed_candle", {})
    state.setdefault("last_processed_close", {})
    state.setdefault("positions", {})
    state.setdefault("signal_diagnostics", [])
    # Persist the clean, branch-specific ledger even when no signal appears.
    save_state(state)

    market_data = get_all_market_data()

    for symbol, data in market_data.items():
        candles = data["candles_5m"]
        if len(candles) < 3:
            continue

        latest_closed = candles[-2]
        latest_id = str(latest_closed["timestamp"])
        last_processed = state["last_processed_candle"].get(symbol)
        if last_processed == latest_id:
            continue

        try:
            pending = get_pending_candles(
                symbol,
                last_processed,
                latest_closed,
                state["last_processed_close"].get(symbol),
            )
        except Exception as error:
            print(f"Recuperación pendiente para {symbol}: {error}")
            continue

        for candle in pending[:-1]:
            process_position_exit(state, symbol, candle)
            state["last_processed_candle"][symbol] = str(candle["timestamp"])
            state["last_processed_close"][symbol] = float(candle["close"])
            save_state(state)

        had_position = symbol in state["positions"]
        process_position_exit(state, symbol, pending[-1])

        # No se abren entradas retrospectivas durante la recuperación del hueco.
        if not had_position and symbol not in state["positions"]:
            open_signal_position(state, symbol, data)

        state["last_processed_candle"][symbol] = latest_id
        state["last_processed_close"][symbol] = float(pending[-1]["close"])
        save_state(state)

    print("Estado del simulador:")
    print(get_status(state))


if __name__ == "__main__":
    run_bot()
