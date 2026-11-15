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

    # Si ambos niveles aparecen dentro de la misma vela, conservamos
    # la regla conservadora existente: stop-loss tiene prioridad.
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


def get_pending_candles(symbol, last_processed, latest_closed):
    """Devuelve velas cerradas posteriores al cursor, sin duplicados."""
    if last_processed is None:
        return [latest_closed]

    recovered = get_candles_since(
        symbol,
        int(last_processed) + 1,
        timeframe="5m"
    )
    latest_timestamp = int(latest_closed["timestamp"])

    unique = {
        int(candle["timestamp"]): candle
        for candle in recovered
        if int(last_processed) < int(candle["timestamp"]) <= latest_timestamp
    }
    pending = [unique[key] for key in sorted(unique)]

    # La última vela presente no basta: verificamos también que no falte
    # ninguna vela de 5 minutos desde el cursor. Ante un hueco, detenemos
    # la recuperación para no saltarnos un posible stop/objetivo.
    expected_timestamp = int(last_processed) + 300000
    for candle in pending:
        candle_timestamp = int(candle["timestamp"])
        if candle_timestamp != expected_timestamp:
            raise RuntimeError(
                f"Recuperación incompleta para {symbol}: "
                f"falta la vela esperada en {expected_timestamp}."
            )
        expected_timestamp += 300000

    # Nunca avanzamos el cursor si la descarga no llegó hasta la última
    # vela cerrada que el feed actual ya conoce.
    if not pending or int(pending[-1]["timestamp"]) != latest_timestamp:
        raise RuntimeError(
            f"Recuperación incompleta para {symbol}: "
            "no se recibió la última vela cerrada."
        )

    return pending


def open_signal_position(state, symbol, data):
    signal = analyze_spot(
        data["candles_5m"],
        data["candles_15m"]
    )

    if not signal or signal["side"] != "BUY":
        return

    candles = data["candles_5m"]
    entry_price = float(candles[-1]["open"])
    stop_price = entry_price - (1.2 * signal["atr"])
    target_price = entry_price + (2 * (entry_price - stop_price))

    success, message = open_position(
        state,
        symbol,
        entry_price,
        stop_price
    )

    if success:
        state["positions"][symbol]["target_price"] = target_price
        save_state(state)

    print(message)


def run_bot():
    state = load_state()
    state.setdefault("last_processed_candle", {})
    state.setdefault("positions", {})

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
                latest_closed
            )
        except Exception as error:
            # No movemos el cursor ante datos incompletos o fallos de API.
            print(f"Recuperación pendiente para {symbol}: {error}")
            continue

        # Durante el hueco solo gestionamos posiciones que ya existían.
        # No inventamos entradas retrospectivas con señales que el bot
        # no pudo observar en tiempo real.
        for candle in pending[:-1]:
            process_position_exit(state, symbol, candle)
            state["last_processed_candle"][symbol] = str(candle["timestamp"])
            save_state(state)

        # La última vela recuperada es la más reciente ya cerrada.
        # Aplicamos primero la gestión de una posición previa.
        had_position = symbol in state["positions"]
        process_position_exit(state, symbol, pending[-1])

        # Las nuevas entradas se evalúan solo en la última vela disponible,
        # nunca retrospectivamente durante la recuperación del hueco.
        if not had_position and symbol not in state["positions"]:
            open_signal_position(state, symbol, data)

        state["last_processed_candle"][symbol] = latest_id
        save_state(state)

    print("Estado del simulador:")
    print(get_status(state))


if __name__ == "__main__":
    run_bot()
