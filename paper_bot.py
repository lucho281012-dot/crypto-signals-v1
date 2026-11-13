from market_data import get_all_market_data
from signal_engine import analyze_spot
from paper_trading import (
    load_state,
    save_state,
    open_position,
    close_position,
    get_status
)


def run_bot():
    state = load_state()
    state.setdefault("last_processed_candle", {})

    market_data = get_all_market_data()

    for symbol, data in market_data.items():
        candles = data["candles_5m"]

        if len(candles) < 3:
            continue

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
                    state, symbol, exit_price, "stop_loss",
                    persist=False
                )

                if success:
                    print(symbol, "STOP LOSS")
                else:
                    print(symbol, message)

            elif target and candle["high"] >= target:
                exit_price = max(candle["open"], target)

                success, message = close_position(
                    state, symbol, exit_price, "take_profit",
                    persist=False
                )

                if success:
                    print(symbol, "TAKE PROFIT")
                else:
                    print(symbol, message)

        else:
            signal = analyze_spot(
                data["candles_5m"],
                data["candles_15m"]
            )

            if signal and signal["side"] == "BUY":
                entry_price = float(candles[-1]["open"])

                stop_price = entry_price - (
                    1.2 * signal["atr"]
                )

                target_price = entry_price + (
                    2 * (entry_price - stop_price)
                )

                success, message = open_position(
                    state,
                    symbol,
                    entry_price,
                    stop_price,
                    persist=False
                )

                if success:
                    state["positions"][symbol]["target_price"] = (
                        target_price
                    )

                print(message)

        # El cambio de posición y su checkpoint se guardan juntos.
        # Si el proceso falla antes de este punto, no se persiste
        # ninguno de los dos cambios para este símbolo.
        state["last_processed_candle"][symbol] = candle_id
        save_state(state)

    print("Estado del simulador:")
    print(get_status(state))


if __name__ == "__main__":
    run_bot()
