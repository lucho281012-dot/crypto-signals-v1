
import json

from historical_data import download_historical_candles
from data_feed import ema, rsi, atr
from signal_rules import evaluate_signal


STOP_ATR = 1.5
REWARD_RISK = 2.0
MAX_HOLDING_BARS = 24

# Supuestos iniciales, no tarifas confirmadas del broker
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0002


def simulate(candles, start, end):
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

        signal = evaluate_signal(indicators)["signal"]

        if signal == "WAIT":
            i += 1
            continue

        direction = 1 if signal == "BUY" else -1
        entry_index = i + 1

        if entry_index > end:
            break

        raw_entry = float(candles[entry_index][1])

        if direction == 1:
            entry = raw_entry * (1 + SLIPPAGE_RATE)
        else:
            entry = raw_entry * (1 - SLIPPAGE_RATE)

        distance = STOP_ATR * indicators["atr_14"]

        if direction == 1:
            stop = entry - distance
            target = entry + distance * REWARD_RISK
        else:
            stop = entry + distance
            target = entry - distance * REWARD_RISK

        last_index = min(
            entry_index + MAX_HOLDING_BARS - 1,
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
            exit_fill = exit_price * (1 - SLIPPAGE_RATE)
        else:
            exit_fill = exit_price * (1 + SLIPPAGE_RATE)

        gross_pct = (
            direction * (exit_fill - entry) / entry
        ) * 100

        fees_pct = (
            FEE_RATE * (entry + exit_fill) / entry
        ) * 100

        net_pct = gross_pct - fees_pct

        trades.append({
            "signal": signal,
            "rsi": round(indicators["rsi_14"], 2),
            "ema_distance_pct": round(
                (indicators["close"] - indicators["ema_50"])
                / indicators["ema_50"] * 100, 4
            ),
            "atr_pct": round(
                indicators["atr_14"] / indicators["close"] * 100, 4
            ),
            "entry_index": entry_index,
            "exit_index": exit_index,
            "entry": round(entry, 2),
            "exit": round(exit_fill, 2),
            "reason": exit_reason,
            "net_return_pct": round(net_pct, 4)
        })

        i = exit_index + 1

    return trades


def summarize(trades):
    if not trades:
        return {"trades": 0}

    results = [t["net_return_pct"] for t in trades]
    wins = [x for x in results if x > 0]
    losses = [x for x in results if x < 0]

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0

    for result in results:
        equity *= 1 + result / 100
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "net_return_compounded_pct": round(
            (equity - 1) * 100, 2
        ),
        "profit_factor": round(
            gross_profit / gross_loss, 3
        ) if gross_loss else None,
        "max_drawdown_pct": round(max_drawdown * 100, 2)
    }


def main():
    candles = download_historical_candles(days=180)

    split = int(len(candles) * 0.70)

    training = simulate(candles, 100, split - 1)
    validation = simulate(candles, split, len(candles) - 1)

    result = {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candles": len(candles),
        "training": summarize(training),
        "validation": summarize(validation),
        "assumptions": {
            "stop_atr": STOP_ATR,
            "reward_risk": REWARD_RISK,
            "max_holding_bars": MAX_HOLDING_BARS,
            "fee_per_side_pct": FEE_RATE * 100,
            "slippage_per_side_pct": SLIPPAGE_RATE * 100,
            "execution": "SIMULATION_ONLY"
        }
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
