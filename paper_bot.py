from market_data import get_all_market_data, get_candles_since
from signal_engine import evaluate_spot
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

    # Incluimos la última vela procesada como semilla para conocer el último
    # cierre negociado. Kraken omite intervalos en los que no hubo trades.
    recovered = get_candles_since(
        symbol,
        last_timestamp,
        timeframe="5m"
    )

    unique = {
        int(candle["timestamp"]): candle
        for candle in recovered
        if last_timestamp <= int(candle["timestamp"]) <= latest_timestamp
    }

    seed = unique.get(last_timestamp)
    if seed is None and last_processed_close is None:
        raise RuntimeError(
            f"Recuperación incompleta para {symbol}: "
            "no se pudo recuperar la vela usada como cursor ni existe "
            "un cierre persistido para reconstruirla."
        )

    # La última vela cerrada conocida por el feed debe existir realmente;
    # no la sustituimos por una vela sintética si falta en la descarga.
    if latest_timestamp not in unique:
        raise RuntimeError(
            f"Recuperación incompleta para {symbol}: "
            "no se recibió la última vela cerrada."
        )

    pending = []
    previous_close = float(seed["close"] if seed is not None else last_processed_close)
    expected_timestamp = last_timestamp + interval_ms

    while expected_timestamp <= latest_timestamp:
        candle = unique.get(expected_timestamp)

        if candle is None:
            # Sin operaciones no hay rango negociado: mantenemos el último
            # precio conocido y volumen cero para poder evaluar el tiempo
            # transcurrido sin inventar movimiento de mercado.
            candle = {
                "timestamp": expected_timestamp,
                "open": previous_close,
                "high": previous_close,
                "low": previous_close,
                "close": previous_close,
                "volume": 0.0
            }
        else:
            previous_close = float(candle["close"])

        pending.append(candle)
        expected_timestamp += interval_ms

    if not pending or int(pending[-1]["timestamp"]) != latest_timestamp:
        raise RuntimeError(
            f"Recuperación incompleta para {symbol}: "
            "no se pudo reconstruir hasta la última vela cerrada."
        )

    return pending


def open_signal_position(state, symbol, data, evaluation=None):
    evaluation = evaluation or evaluate_spot(data['candles_5m'], data['candles_15m'])
    if not evaluation:
        return

    signal = evaluation['signal']
    diagnostic = dict(evaluation['diagnostic'])
    diagnostic['symbol'] = symbol
    diagnostic['entry_blocked_reason'] = None
    diagnostics = state.setdefault('signal_diagnostics', [])
    key = (symbol, diagnostic['candle_timestamp'])
    if not any((item.get('symbol'), item.get('candle_timestamp')) == key for item in diagnostics):
        diagnostics.append(diagnostic)

    if not signal or signal['side'] != 'BUY':
        save_state(state)
        return

    candles = data['candles_5m']
    entry_price = float(candles[-1]['open'])
    stop_price = entry_price - (1.2 * signal['atr'])
    target_price = entry_price + (2 * (entry_price - stop_price))
    success, message = open_position(state, symbol, entry_price, stop_price, signal_diagnostic=diagnostic)
    if success:
        state['positions'][symbol]['target_price'] = target_price
        save_state(state)
    else:
        diagnostic['entry_blocked_reason'] = message
        save_state(state)
    print(message)

def run_bot():
    state = load_state()
    state.setdefault("last_processed_candle", {})
    state.setdefault("last_processed_close", {})
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
                latest_closed,
                state["last_processed_close"].get(symbol)
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
            state["last_processed_close"][symbol] = float(candle["close"])
            save_state(state)

        # La última vela recuperada es la más reciente ya cerrada.
        # Aplicamos primero la gestión de una posición previa.
        had_position = symbol in state["positions"]
        process_position_exit(state, symbol, pending[-1])

        # Las nuevas entradas se evalúan solo en la última vela disponible,
        # nunca retrospectivamente durante la recuperación del hueco.
        # Diagnostics are recorded even when an existing position blocks a new entry.
        evaluation = evaluate_spot(data["candles_5m"], data["candles_15m"])
        if evaluation:
            if had_position or symbol in state["positions"]:
                diagnostic = dict(evaluation["diagnostic"])
                diagnostic["symbol"] = symbol
                diagnostic["entry_blocked_reason"] = "existing_position"
                diagnostics = state.setdefault("signal_diagnostics", [])
                key = (symbol, diagnostic["candle_timestamp"])
                if not any((item.get("symbol"), item.get("candle_timestamp")) == key for item in diagnostics):
                    diagnostics.append(diagnostic)
            else:
                open_signal_position(state, symbol, data, evaluation)

        state["last_processed_candle"][symbol] = latest_id
        state["last_processed_close"][symbol] = float(pending[-1]["close"])
        save_state(state)

    print("Estado del simulador:")
    print(get_status(state))


if __name__ == "__main__":
    run_bot()
