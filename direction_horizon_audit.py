
import json

from historical_data import download_historical_candles
from data_feed import ema, rsi, atr
from signal_rules import evaluate_signal

# =========================================================
# MT5 SIGNALS - DIRECTION / HORIZON AUDIT
# BTCUSDT / H1
# BUY vs SELL
# 18 vs 24 candles
# SIMULATION ONLY - NO REAL ORDERS
# =========================================================

STOP_ATR = 1.5
REWARD_RISK = 2.0

FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0002

HORIZONS = [18, 24]
BLOCK_COUNT = 4
WARMUP_BARS = 100


def simulate(candles, max_holding_bars):

    if not isinstance(candles, list):
        raise ValueError("Candles must be a list")

    if len(candles) < 200:
        raise ValueError("Insufficient historical candles")

    if max_holding_bars < 1:
        raise ValueError("Invalid maximum holding period")

    trades = []
    end = len(candles) - 1

    i = WARMUP_BARS

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

        # Entry on next candle open.
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
            entry_index + max_holding_bars - 1,
            end
        )

        exit_price = None
        exit_reason = "TIME_LIMIT"
        exit_index = last_index

        # =================================================
        # EXIT SIMULATION
        # =================================================

        for j in range(entry_index, last_index + 1):

            candle_open = float(candles[j][1])
            high = float(candles[j][2])
            low = float(candles[j][3])

            if direction == 1:

                if candle_open <= stop:
                    exit_price = candle_open
                    exit_reason = "STOP_LOSS"
                    exit_index = j
                    break

                if candle_open >= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_index = j
                    break

                stop_hit = low <= stop
                target_hit = high >= target

            else:

                if candle_open >= stop:
                    exit_price = candle_open
                    exit_reason = "STOP_LOSS"
                    exit_index = j
                    break

                if candle_open <= target:
                    exit_price = target
                    exit_reason = "TAKE_PROFIT"
                    exit_index = j
                    break

                stop_hit = high >= stop
                target_hit = low <= target

            # Conservative: stop has priority.
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

        # Time-limit exit.
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
            "entry_index": entry_index,
            "exit_index": exit_index,
            "reason": exit_reason,
            "net_return_pct": round(net_pct, 4)
        })

        # Prevent overlapping positions.
        i = exit_index + 1

    return trades


def summarize(trades):

    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0,
            "average_net_return_pct": 0,
            "total_net_return_pct": 0,
            "compounded_return_pct": 0,
            "profit_factor": None,
            "max_drawdown_pct": 0
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

        "average_net_return_pct": round(
            sum(results) / len(results),
            4
        ),

        "total_net_return_pct": round(
            sum(results),
            4
        ),

        "compounded_return_pct": round(
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


def build_blocks(candles):

    start = WARMUP_BARS
    end = len(candles) - 1

    usable_bars = end - start + 1
    block_size = usable_bars // BLOCK_COUNT

    blocks = []

    for block_number in range(BLOCK_COUNT):

        block_start = start + block_number * block_size

        if block_number == BLOCK_COUNT - 1:
            block_end = end
        else:
            block_end = block_start + block_size - 1

        blocks.append({
            "block": block_number + 1,
            "start_index": block_start,
            "end_index": block_end
        })

    return blocks


def filter_direction(trades, direction):

    return [
        trade for trade in trades
        if trade["signal"] == direction
    ]


def analyze_horizon(candles, horizon, blocks):

    trades = simulate(
        candles,
        max_holding_bars=horizon
    )

    result = {
        "overall": summarize(trades),

        "directions": {
            "BUY": summarize(
                filter_direction(trades, "BUY")
            ),

            "SELL": summarize(
                filter_direction(trades, "SELL")
            )
        },

        "blocks": []
    }

    for block in blocks:

        block_trades = [
            trade for trade in trades
            if (
                block["start_index"]
                <= trade["entry_index"]
                <= block["end_index"]
            )
        ]

        result["blocks"].append({
            "block": block["block"],
            "start_index": block["start_index"],
            "end_index": block["end_index"],

            "overall": summarize(block_trades),

            "BUY": summarize(
                filter_direction(block_trades, "BUY")
            ),

            "SELL": summarize(
                filter_direction(block_trades, "SELL")
            )
        })

    return result


def main():

    candles = download_historical_candles(days=365)

    if len(candles) < 1000:
        raise ValueError(
            "Insufficient historical candles for audit"
        )

    blocks = build_blocks(candles)

    results = {}

    for horizon in HORIZONS:

        results[str(horizon)] = analyze_horizon(
            candles,
            horizon,
            blocks
        )

    output = {
        "status": "success",
        "symbol": "BTCUSDT",
        "timeframe": "H1",
        "candles": len(candles),

        "method": (
            "Full-history simulation; trades assigned "
            "to blocks by entry index"
        ),

        "horizons": HORIZONS,
        "results": results,

        "assumptions": {
            "stop_atr": STOP_ATR,
            "reward_risk": REWARD_RISK,
            "fee_per_side_pct": FEE_RATE * 100,
            "slippage_per_side_pct": SLIPPAGE_RATE * 100,
            "gap_stop_protection": True,
            "same_candle_priority": "STOP_LOSS",
            "overlapping_positions": False,
            "execution": "SIMULATION_ONLY"
        }
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
