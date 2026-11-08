import json

import backtest
from historical_data import download_historical_candles
from data_feed import ema, rsi, atr
from signal_rules import evaluate_signal


# Filtros experimentales.
# No modifican la estrategia original.

EMA_SLOPE_BARS = 3

ATR_MIN_PCT = 0.4
ATR_MAX_PCT = 0.8


def apply_filter(filter_name, signal, indicators):
    if signal == "WAIT":
        return "WAIT"

    close = indicators["close"]
    ema_now = indicators["ema_50"]
    rsi_value = indicators["rsi_14"]
    atr_pct = indicators["atr_pct"]

    slope_up = indicators["ema_slope_up"]
    slope_down = indicators["ema_slope_down"]

    bullish_candle = indicators["bullish_candle"]
    bearish_candle = indicators["bearish_candle"]

    if filter_name in ("BASELINE",):
        return signal

    if filter_name in ("EMA_SLOPE", "EMA_PLUS_CANDLE", "ALL_FILTERS"):
        if signal == "BUY" and not slope_up:
            return "WAIT"

        if signal == "SELL" and not slope_down:
            return "WAIT"

    if filter_name in ("CANDLE_CONFIRM", "EMA_PLUS_CANDLE", "ALL_FILTERS"):
        if signal == "BUY" and not bullish_candle:
            return "WAIT"

        if signal == "SELL" and not bearish_candle:
            return "WAIT"

    if filter_name in ("ATR_RANGE", "ALL_FILTERS"):
        if not ATR_MIN_PCT <= atr_pct <= ATR_MAX_PCT:
            return "WAIT"

    if filter_name in ("RSI_NARROW", "ALL_FILTERS"):
        if signal == "BUY" and not 55 <= rsi_value <= 65:
            return "WAIT"

        if signal == "SELL" and not 35 <= rsi_value <= 45:
            return "WAIT"

    return signal


def simulate_filtered(candles, start, end, filter_name):
    trades = []
    i = max(start, 100)

    while i < end:
        history = candles[:i + 1]

        closes = [float(c[4]) for c in history]

        indicators = {
            "close": closes[-1],
            "ema_50": ema(closes, 50),
            "rsi_14": rsi(closes, 14),
            "atr_14": atr(history, 14)
        }

        # EMA de hace tres velas para medir su pendiente.
        previous_closes = closes[:-EMA_SLOPE_BARS]

        previous_ema = ema(previous_closes, 50)

        current_ema = indicators["ema_50"]

        indicators["ema_slope_up"] = current_ema > previous_ema
        indicators["ema_slope_down"] = current_ema < previous_ema

        # Confirmación de la vela que ya cerró.
        current_candle = candles[i]

        candle_open = float(current_candle[1])
        candle_close = float(current_candle[4])

        indicators["bullish_candle"] = candle_close > candle_open
        indicators["bearish_candle"] = candle_close < candle_open

        indicators["atr_pct"] = (
            indicators["atr_14"] / indicators["close"] * 100
        )

        original_signal = evaluate_signal(indicators)["signal"]

        signal = apply_filter(
            filter_name,
            original_signal,
            indicators
        )

        if signal == "WAIT":
            i += 1
            continue

        direction = 1 if signal == "BUY" else -1
        entry_index = i + 1

        if entry_index > end:
            break

        raw_entry = float(candles[entry_index][1])

        if direction == 1:
            entry = raw_entry * (1 + backtest.SLIPPAGE_RATE)
        else:
            entry = raw_entry * (1 - backtest.SLIPPAGE_RATE)

        distance = backtest.STOP_ATR * indicators["atr_14"]

        if direction == 1:
            stop = entry - distance
            target = entry + distance * backtest.REWARD_RISK
        else:
            stop = entry + distance
            target = entry - distance * backtest.REWARD_RISK

        last_index = min(
            entry_index + backtest.MAX_HOLDING_BARS - 1,
            end
        )

        exit_price = None
        exit_reason = "TIME_LIMIT"
        exit_index = last_index

        for j in range(entry_index, last_index + 1):
            high = float(candles[j][2])
            low = float(candles[j][3])

            if direction == 1:
                stop_hit = low <= stop
                target_hit = high >= target
            else:
                stop_hit = high >= stop
                target_hit = low <= target

            # Si ambos niveles aparecen tocados en la misma vela,
            # se contabiliza primero el stop, de forma conservadora.
            if stop_hit:
                exit_price = stop
                exit_reason = "STOP_LOSS"
                exit_index = j
                break

            if target_hit:
                exit_price = target
                exit_reason = "TAKE_PROFIT"
                exit_index = j
                break

        if exit_price is None:
            exit_price = float(candles[last_index][4])

        if direction == 1:
            exit_fill = exit_price * (1 - backtest.SLIPPAGE_RATE)
        else:
            exit_fill = exit_price * (1 + backtest.SLIPPAGE_RATE)

        gross_pct = (
            direction * (exit_fill - entry) / entry
        ) * 100

        fees_pct = (
            backtest.FEE_RATE * (entry + exit_fill) / entry
        ) * 100

        net_pct = gross_pct - fees_pct

        trades.append({
            "signal": signal,
            "entry_index": entry_index,
            "exit_index": exit_index,
            "reason": exit_reason,
            "net_return_pct": round(net_pct, 4)
        })

        i = exit_index + 1

    return trades


def summarize(trades):
    if not trades:
        return {
            "trades": 0,
            "message": "No trades"
        }

    returns = [t["net_return_pct"] for t in trades]

    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]

    positive = sum(wins)
    negative = abs(sum(losses))

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0

    for result in returns:
        equity *= 1 + result / 100
        peak = max(peak, equity)

        drawdown = (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "expectancy_pct": round(sum(returns) / len(returns), 4),
        "profit_factor": round(
            positive / negative, 3
        ) if negative else None,
        "compound_return_diagnostic_pct": round(
            (equity - 1) * 100, 2
        ),
        "max_drawdown_diagnostic_pct": round(
            max_drawdown * 100, 2
        )
    }


def trade_signature(trades):
    return [
        (
            t["signal"],
            t["entry_index"],
            t["exit_index"],
            t["net_return_pct"]
        )
        for t in trades
    ]


def main():
    candles = download_historical_candles(days=365)

    if len(candles) < 500:
        raise ValueError("Not enough historical candles")

    filters = [
        "BASELINE",
        "EMA_SLOPE",
        "CANDLE_CONFIRM",
        "ATR_RANGE",
        "RSI_NARROW",
        "EMA_PLUS_CANDLE",
        "ALL_FILTERS"
    ]

    # Comprobar que el simulador BASELINE coincide
    # con el backtest original en todo el período.
    baseline_original = backtest.simulate(
        candles, 100, len(candles) - 1
    )

    baseline_audit = simulate_filtered(
        candles, 100, len(candles) - 1, "BASELINE"
    )

    baseline_matches = (
        trade_signature(baseline_original)
        == trade_signature(baseline_audit)
    )

    if not baseline_matches:
        raise RuntimeError(
            "BASELINE mismatch: audit simulation differs "
            "from backtest.py"
        )

    # Cuatro bloques cronológicos consecutivos.
    usable_bars = len(candles) - 100
    block_size = usable_bars // 4

    blocks = []

    for block_number in range(4):
        start = 100 + block_number * block_size

        if block_number == 3:
            end = len(candles) - 1
        else:
            end = start + block_size - 1

        blocks.append((start, end))

    results = {}

        for filter_name in filters:
        results[filter_name] = {
            "blocks": [],
            "overall": {},
            "by_direction": {
                "BUY": {"blocks": []},
                "SELL": {"blocks": []}
            }
        }

        all_trades = []

        for block_number, (start, end) in enumerate(blocks, 1):
            trades = simulate_filtered(
                candles,
                start,
                end,
                filter_name
            )

            all_trades.extend(trades)

            results[filter_name]["blocks"].append({
                "block": block_number,
                "start_index": start,
                "end_index": end,
                **summarize(trades)
            })

            for direction in ["BUY", "SELL"]:
                directional_trades = [
                    t for t in trades
                    if t["signal"] == direction
                ]

                results[filter_name]["by_direction"][direction]["blocks"].append({
                    "block": block_number,
                    **summarize(directional_trades)
                })

        results[filter_name]["overall"] = summarize(all_trades)

        for direction in ["BUY", "SELL"]:
            directional_trades = [
                t for t in all_trades
                if t["signal"] == direction
            ]

            results[filter_name]["by_direction"][direction]["overall"] = (
                summarize(directional_trades)
                )

    result = {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candles": len(candles),
        "baseline_matches_original_backtest": baseline_matches,
        "filters": results,
        "parameters": {
            "ema_slope_bars": EMA_SLOPE_BARS,
            "atr_min_pct": ATR_MIN_PCT,
            "atr_max_pct": ATR_MAX_PCT,
            "stop_atr": backtest.STOP_ATR,
            "reward_risk": backtest.REWARD_RISK,
            "max_holding_bars": backtest.MAX_HOLDING_BARS
        },
        "note": (
            "Exploratory filter audit only. No real orders. "
            "Compound return assumes full capital exposure "
            "per trade and is diagnostic, not an account forecast. "
            "Filters are hypotheses, not proven improvements."
        )
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
