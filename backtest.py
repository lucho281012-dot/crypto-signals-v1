
import json

from historical_data import download_historical_candles
from data_feed import ema, rsi, atr
from signal_rules import evaluate_signal

# =========================================================
# MT5 SIGNALS - BACKTEST ENGINE
# BTCUSDT / H1
# SIMULATION ONLY - NO REAL ORDERS
# =========================================================

STOP_ATR = 1.5
REWARD_RISK = 2.0
MAX_HOLDING_BARS = 24

FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0002


def simulate(candles, start, end):

    if not isinstance(candles, list):
        raise ValueError("Candles must be a list")

    if start < 0 or end < 0:
        raise ValueError("Invalid simulation indexes")

    if start > end:
        raise ValueError("Start index cannot exceed end index")

    if end >= len(candles):
        raise ValueError("End index exceeds available candles")

    if MAX_HOLDING_BARS < 1:
        raise ValueError("Invalid maximum holding period")

    trades = []

    i = max(start, 100)

    while i < end:

        history = candles[:i + 1]

        closes = [
            float(candle[4])
            for candle in history
        ]

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

        # Entry on the next candle open.
        entry_index = i + 1

        if entry_index > end:
            break

        raw_entry = float(candles[entry_index][1])

        # Adverse entry slippage.
        if direction == 1:
            entry = raw_entry * (1 + SLIPPAGE_RATE)
        else:
            entry = raw_entry * (1 - SLIPPAGE_RATE)

        distance = STOP_ATR * indicators["atr_14"]

        if distance <= 0:
            i += 1
            continue

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

        # =================================================
        # EXIT SIMULATION
        # Includes gap-through-stop protection.
        # =================================================

        for j in range(entry_index, last_index + 1):

            candle_open = float(candles[j][1])
            high = float(candles[j][2])
            low = float(candles[j][3])

            if direction == 1:

                # Gap below stop: execute at candle open.
                if candle_open <= stop:
                    exit_price = candle_open
                    exit_reason = "STOP_LOSS"
                    exit_index = j
                    break

                # Gap above target: conservative target fill.
                if candle_open >= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_index = j
                    break

                stop_hit = low <= stop
                target_hit = high >= target

            else:

                # Gap above stop: execute at candle open.
                if candle_open >= stop:
                    exit_price = candle_open
                    exit_reason = "STOP_LOSS"
                    exit_index = j
                    break

                # Gap below target: conservative target fill.
                if candle_open <= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_index = j
                    break

                stop_hit = high >= stop
                target_hit = low <= target

            # Conservative assumption:
            # If SL and TP occur in the same candle,
            # assume the stop was reached first.

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

        # Time-limit exit at last closed candle.
        if exit_price is None:
            exit_price = float(candles[last_index][4])

        # Adverse exit slippage.
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
                (
                    indicators["close"]
                    - indicators["ema_50"]
                ) / indicators["ema_50"] * 100,
                4
            ),
            "atr_pct": round(
                indicators["atr_14"]
                / indicators["close"] * 100,
                4
            ),
            "entry_index": entry_index,
            "exit_index": exit_index,
            "entry": round(entry, 2),
            "exit": round(exit_fill, 2),
            "reason": exit_reason,
            "net_return_pct": round(net_pct, 4)
        })

        # Prevent overlapping positions.
        i = exit_index + 1

    return trades


def summarize(trades):

    if not trades:
        return {
            "trades": 0
        }

    results = [
        trade["net_return_pct"]
        for trade in trades
    ]

    wins = [
        result for result in results
        if result > 0
    ]

    losses = [
        result for result in results
        if result < 0
    ]

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0

    for result in results:

        equity *= 1 + result / 100

        peak = max(peak, equity)

        drawdown = (peak - equity) / peak

        max_drawdown = max(
            max_drawdown,
            drawdown
        )

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(
            len(wins) / len(trades) * 100,
            2
        ),
        "net_return_compounded_pct": round(
            (equity - 1) * 100,
            2
        ),
        "profit_factor": round(
            gross_profit / gross_loss,
            3
        ) if gross_loss else None,
        "max_drawdown_pct": round(
            max_drawdown * 100,
            2
        )
    }


def main():

    candles = download_historical_candles(days=180)

    if len(candles) < 200:
        raise ValueError(
            "Insufficient historical candles"
        )

    split = int(len(candles) * 0.70)

    training = simulate(
        candles,
        100,
        split - 1
    )

    validation = simulate(
        candles,
        split,
        len(candles) - 1
    )

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
            "gap_stop_protection": True,
            "same_candle_priority": "STOP_LOSS",
            "execution": "SIMULATION_ONLY"
        }
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
