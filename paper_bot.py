from datetime import datetime, timezone

from market_data import get_all_market_data, get_candles_since
from signal_engine import analyze_spot
from paper_trading import (
    load_state,
    save_state,
    open_positions_batch,
    close_position,
    get_status,
    SLIPPAGE_BPS,
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
        # A stop-market exit pays adverse slippage, including on gap opens.
        raw_exit = min(float(candle["open"]), float(stop))
        exit_price = raw_exit * (1.0 - SLIPPAGE_BPS / 10000.0)
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


def _iso_from_ms(timestamp_ms):
    return datetime.fromtimestamp(
        int(timestamp_ms) / 1000.0, tz=timezone.utc
    ).isoformat()


def build_entry_candidate(
    state, symbol, data, now_ms=None,
    max_quote_age_ms=60000, max_signal_age_ms=300000,
    max_trend_age_ms=900000
):
    """Build a paper entry only from a timestamped quote observed after signal close.

    The strategy signal is calculated from completed candles. The fill reference
    is the later ticker price, never the open of the already-running candle.
    """
    if symbol in state.get("positions", {}):
        return None

    candles_5m = data.get("candles_5m", [])
    candles_15m = data.get("candles_15m", [])
    if len(candles_5m) < 3 or len(candles_15m) < 3:
        return None

    signal = analyze_spot(candles_5m, candles_15m)
    if not signal or signal.get("side") != "BUY":
        return None

    quote_price = data.get("price")
    quote_timestamp = data.get("price_timestamp")
    if quote_price is None or quote_timestamp is None:
        return None

    quote_price = float(quote_price)
    quote_timestamp = int(quote_timestamp)
    if quote_price <= 0:
        return None

    signal_candle_timestamp = int(candles_5m[-2]["timestamp"])
    signal_close_ms = signal_candle_timestamp + 300000
    trend_candle_timestamp = int(candles_15m[-2]["timestamp"])
    trend_close_ms = trend_candle_timestamp + 900000
    decision_ms = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)

    # Reject stale candles even if the ticker itself is fresh.
    if decision_ms - signal_close_ms > int(max_signal_age_ms):
        return None
    if trend_close_ms > decision_ms + 5000:
        return None
    if decision_ms - trend_close_ms > int(max_trend_age_ms):
        return None

    # A quote before the signal candle closed cannot be used as its execution price.
    if quote_timestamp < signal_close_ms:
        return None
    # Reject stale or implausibly future-dated quotes.
    if quote_timestamp > decision_ms + 5000:
        return None
    if decision_ms - quote_timestamp > int(max_quote_age_ms):
        return None

    # Apply adverse entry slippage to the ask reference before sizing.
    entry_price = quote_price * (1.0 + SLIPPAGE_BPS / 10000.0)
    atr = float(signal["atr"])
    if atr <= 0:
        return None

    stop_price = entry_price - 1.2 * atr
    if stop_price <= 0 or stop_price >= entry_price:
        return None
    target_price = entry_price + 2.0 * (entry_price - stop_price)

    return {
        "symbol": symbol,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "signal_candle_timestamp": signal_candle_timestamp,
        "signal_confirmed_at": _iso_from_ms(signal_close_ms),
        "entry_decision_at": _iso_from_ms(decision_ms),
        "entry_candle_timestamp": (quote_timestamp // 300000) * 300000,
        "quote_timestamp": _iso_from_ms(quote_timestamp),
        "quote_price": quote_price,
        "quote_side": "ask",
        "entry_delay_seconds": round((quote_timestamp - signal_close_ms) / 1000.0, 3),
        "strategy_version": "crypto-signals-v1-2",
        "signal_snapshot": {
            "side": signal["side"],
            "atr": atr,
            "rsi": signal.get("rsi"),
            "conditions_met": signal.get("conditions_met"),
            "signal_close": signal.get("entry"),
        },
    }

def open_signal_position(state, symbol, data):
    """Compatibility wrapper returning a candidate, not opening it immediately."""
    return build_entry_candidate(state, symbol, data)


def run_bot():
    state = load_state()
    state.setdefault("last_processed_candle", {})
    state.setdefault("last_processed_close", {})
    state.setdefault("positions", {})

    market_data = get_all_market_data()
    entry_candidates = []
    processed_any = False

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
            # No cursor movement if recovery is incomplete or the API fails.
            print(f"Recuperación pendiente para {symbol}: {error}")
            continue

        # Manage old positions over each recovered candle; never open
        # retrospectively during a gap.
        for candle in pending[:-1]:
            process_position_exit(state, symbol, candle)
            state["last_processed_candle"][symbol] = str(candle["timestamp"])
            state["last_processed_close"][symbol] = float(candle["close"])
            save_state(state)

        had_position = symbol in state["positions"]
        process_position_exit(state, symbol, pending[-1])

        # Collect all new signals first. They are sized together after every
        # symbol has been processed, so simultaneous signals share one budget.
        if not had_position and symbol not in state["positions"]:
            candidate = open_signal_position(state, symbol, data)
            if isinstance(candidate, dict):
                entry_candidates.append(candidate)

        state["last_processed_candle"][symbol] = latest_id
        state["last_processed_close"][symbol] = float(pending[-1]["close"])
        processed_any = True

    if entry_candidates:
        results = open_positions_batch(state, entry_candidates)
        for symbol, (success, message) in results.items():
            print(message)
        # A successful batch already persisted positions and all updated
        # cursors together. If every candidate was rejected, persist cursors.
        if processed_any and not any(success for success, _ in results.values()):
            save_state(state)
    elif processed_any:
        save_state(state)

    print("Estado del simulador:")
    print(get_status(state))


if __name__ == "__main__":
    run_bot()
