
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

            # Si ambos niveles se alcanzan en la misma vela,
            # asumimos conservadoramente que se ejecutó el stop.
            if candle["low"] <= stop:
                exit_price = min(candle["open"], stop)
                close_position(
                    state, symbol, exit_price, "stop_loss"
                )
                print(symbol, "STOP LOSS")

            elif target and candle["high"] >= target:
                exit_price = max(candle["open"], target)
                close_position(
                    state, symbol, exit_price, "take_profit"
                )
                print(symbol, "TAKE PROFIT")

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
                    stop_price
                )

                if success:
                    state["positions"][symbol]["target_price"] = (
                        target_price
                    )
                    save_state(state)

                print(message)

        state["last_processed_candle"][symbol] = candle_id
        save_state(state)

    print("Estado del simulador:")
    print(get_status(state))


if __name__ == "__main__":
    run_bot()
