from market_data import get_all_market_data, get_candles_since
from signal_engine import analyze_spot
from paper_trading import (
    load_state,
    save_state,
    open_positions,
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
        raise RuntimeError(f"Cursor o vela fuera de alineación de 5 minutos para {symbol}.")
    recovered = get_candles_since(symbol, last_timestamp, timeframe="5m")
    unique = {int(c["timestamp"]): c for c in recovered
              if last_timestamp <= int(c["timestamp"]) <= latest_timestamp}
    seed = unique.get(last_timestamp)
    if seed is None and last_processed_close is None:
        raise RuntimeError(f"Recuperación incompleta para {symbol}: falta semilla y cierre persistido.")
    if latest_timestamp not in unique:
        raise RuntimeError(f"Recuperación incompleta para {symbol}: falta última vela cerrada.")
    pending = []
    previous_close = float(seed["close"] if seed is not None else last_processed_close)
    expected = last_timestamp + interval_ms
    while expected <= latest_timestamp:
        candle = unique.get(expected)
        if candle is None:
            candle = {"timestamp": expected, "open": previous_close, "high": previous_close,
                      "low": previous_close, "close": previous_close, "volume": 0.0}
        else:
            previous_close = float(candle["close"])
        pending.append(candle)
        expected += interval_ms
    if not pending or int(pending[-1]["timestamp"]) != latest_timestamp:
        raise RuntimeError(f"Recuperación incompleta para {symbol}: no se alcanzó última vela.")
    return pending


def build_signal_position_request(symbol, data):
    """Prepara una señal sin abrirla para repartir el presupuesto entre todo el ciclo."""
    signal = analyze_spot(data["candles_5m"], data["candles_15m"])
    if not signal or signal["side"] != "BUY":
        return None
    entry = float(data["candles_5m"][-1]["open"])
    stop = entry - (1.2 * signal["atr"])
    target = entry + (2 * (entry - stop))
    return {"symbol": symbol, "entry_price": entry, "stop_price": stop,
            "target_price": target}


def open_signal_position(state, symbol, data):
    """Compatibilidad con pruebas anteriores; prepara una solicitud para el lote."""
    return build_signal_position_request(symbol, data)


def run_bot():
    state = load_state()
    state.setdefault("last_processed_candle", {})
    state.setdefault("last_processed_close", {})
    state.setdefault("positions", {})
    market_data = get_all_market_data()
    entry_requests = []
    latest_cursor_updates = []

    # Primero se procesan las salidas y se reúnen todas las nuevas señales.
    # Ninguna señal consume el presupuesto antes de conocer las demás del ciclo.
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
                symbol, last_processed, latest_closed,
                state["last_processed_close"].get(symbol))
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
        if not had_position and symbol not in state["positions"]:
            request = open_signal_position(state, symbol, data)
            if isinstance(request, dict):
                entry_requests.append(request)
        # Persistir los cursores más recientes después de validar el lote permite reintentar.
        latest_cursor_updates.append((symbol, latest_id, float(pending[-1]["close"])))

    if entry_requests:
        try:
            results = open_positions(state, entry_requests)
        except (ValueError, KeyError, TypeError, AssertionError) as error:
            print(f"Lote de entradas rechazado; se reintentará la vela: {error}")
            return
        for success, message in results:
            print(message)

    for symbol, latest_id, latest_close in latest_cursor_updates:
        state["last_processed_candle"][symbol] = latest_id
        state["last_processed_close"][symbol] = latest_close
    if latest_cursor_updates:
        save_state(state)

    print("Estado del simulador:")
    print(get_status(state))


if __name__ == "__main__":
    run_bot()
