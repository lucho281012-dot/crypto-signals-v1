"""Historical, fee-aware research backtest. Does not place orders or modify paper state."""
import json
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
FEE_RATE = 0.001
RISK_FRACTION = 0.01
MAX_POSITION_FRACTION = 0.95
CANDLE_LIMIT = 720
TIMEFRAME_MS = {"5m": 300_000, "15m": 900_000}
STOP_MULTIPLIERS = [1.0, 1.2, 1.5, 2.0]
REWARD_RATIOS = [1.5, 2.0, 2.5, 3.0]
OUTPUT = Path("strategy_research_report.json")


def calculate_indicators(candles):
    df = pd.DataFrame(candles).copy()
    close = df["close"]
    volume = df["volume"]
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["volume_sma20"] = volume.rolling(20).mean()
    previous_close = close.shift(1)
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(14).mean()
    return df


def has_buy_signal(index, five, fifteen):
    current = five.iloc[index]
    close_time = int(current["timestamp"]) + TIMEFRAME_MS["5m"]
    eligible = fifteen[
        fifteen["timestamp"] + TIMEFRAME_MS["15m"] <= close_time
    ]
    if eligible.empty or current[["ema20", "ema200", "rsi", "macd",
                                  "macd_signal", "volume_sma20", "atr"]].isna().any():
        return None
    trend = eligible.iloc[-1]
    if trend[["ema20", "ema200"]].isna().any():
        return None
    conditions = [
        current["ema20"] > current["ema200"],
        current["rsi"] > 50,
        current["macd"] > current["macd_signal"],
        current["volume"] > current["volume_sma20"],
        current["close"] > current["ema20"],
    ]
    if sum(conditions) >= 4 and trend["ema20"] > trend["ema200"] and current["atr"] > 0:
        return float(current["atr"])
    return None


def calculate_quantity(equity, entry, stop, risk_fraction=RISK_FRACTION):
    risk_per_unit = entry - stop + entry * FEE_RATE + stop * FEE_RATE
    if equity <= 0 or entry <= stop or risk_per_unit <= 0:
        return 0.0
    risk_quantity = equity * risk_fraction / risk_per_unit
    capital_quantity = equity * MAX_POSITION_FRACTION / (entry * (1 + FEE_RATE))
    return max(0.0, min(risk_quantity, capital_quantity))


def resolve_exit(position, candle):
    # Conservative rule: if stop and target occur in one candle, stop wins.
    if candle["low"] <= position["stop"]:
        return min(candle["open"], position["stop"]), "stop_loss"
    if candle["high"] >= position["target"]:
        return max(candle["open"], position["target"]), "take_profit"
    return None


def _close_trade(position, exit_price, reason, timestamp):
    exit_fee = position["quantity"] * exit_price * FEE_RATE
    pnl = (
        position["quantity"] * (exit_price - position["entry"])
        - position["entry_fee"] - exit_fee
    )
    return {
        "entry_timestamp": int(position["entry_timestamp"]),
        "exit_timestamp": int(timestamp),
        "entry_price": position["entry"],
        "exit_price": float(exit_price),
        "quantity": position["quantity"],
        "entry_fee": position["entry_fee"],
        "exit_fee": exit_fee,
        "net_pnl": pnl,
        "reason": reason,
    }


def simulate(five, fifteen, stop_multiplier, reward_ratio,
             start_index, end_index, initial_balance=100.0):
    equity = float(initial_balance)
    peak = equity
    max_drawdown = 0.0
    trades = []
    position = None
    first_index = max(200, int(start_index))
    end_index = min(int(end_index), len(five))

    for index in range(first_index, end_index):
        candle = five.iloc[index]
        had_position = position is not None

        if position is not None:
            exit_event = resolve_exit(position, candle)
            if exit_event:
                exit_price, reason = exit_event
                trade = _close_trade(position, exit_price, reason, candle["timestamp"])
                trades.append(trade)
                equity += trade["net_pnl"]
                position = None
                peak = max(peak, equity)
                if peak > 0:
                    max_drawdown = max(max_drawdown, (peak - equity) / peak)

        # Do not re-enter on the same candle that closed an existing trade.
        if not had_position and position is None and index + 1 < end_index:
            atr = has_buy_signal(index, five, fifteen)
            if atr:
                next_candle = five.iloc[index + 1]
                entry = float(next_candle["open"])
                stop = entry - stop_multiplier * atr
                if stop > 0 and stop < entry:
                    quantity = calculate_quantity(equity, entry, stop)
                    if quantity > 0:
                        entry_fee = quantity * entry * FEE_RATE
                        position = {
                            "entry": entry,
                            "entry_timestamp": int(next_candle["timestamp"]),
                            "stop": stop,
                            "target": entry + reward_ratio * (entry - stop),
                            "quantity": quantity,
                            "entry_fee": entry_fee,
                        }

    if position is not None and end_index > first_index:
        last = five.iloc[end_index - 1]
        trade = _close_trade(position, float(last["close"]), "end_of_sample",
                             last["timestamp"])
        trades.append(trade)
        equity += trade["net_pnl"]
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    wins = [trade["net_pnl"] for trade in trades if trade["net_pnl"] > 0]
    losses = [-trade["net_pnl"] for trade in trades if trade["net_pnl"] < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_percent": round(len(wins) / len(trades) * 100, 4) if trades else None,
        "net_pnl_usdt": round(equity - initial_balance, 8),
        "return_percent": round((equity / initial_balance - 1) * 100, 6),
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "max_closed_trade_drawdown_percent": round(max_drawdown * 100, 6),
        "fees_usdt": round(sum(t["entry_fee"] + t["exit_fee"] for t in trades), 8),
        "trade_log": trades,
    }


def fetch_history(exchange, symbol, timeframe):
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=CANDLE_LIMIT)
    now = exchange.milliseconds()
    interval = TIMEFRAME_MS[timeframe]
    closed = [row for row in raw if int(row[0]) + interval <= now]
    if len(closed) < 220:
        raise RuntimeError(f"Histórico insuficiente para {symbol} {timeframe}: {len(closed)} velas cerradas")
    return [
        {"timestamp": int(r[0]), "open": float(r[1]), "high": float(r[2]),
         "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
        for r in closed
    ]



def signal_diagnostics(five, fifteen):
    counts = {
        "bars_checked_after_warmup": 0,
        "bars_with_valid_indicators": 0,
        "bullish_15m_trend_bars": 0,
        "bars_with_at_least_4_of_5_5m_conditions": 0,
        "actual_buy_signal_bars": 0,
        "condition_pass_counts": {
            "ema20_above_ema200": 0,
            "rsi_above_50": 0,
            "macd_above_signal": 0,
            "volume_above_sma20": 0,
            "close_above_ema20": 0,
        },
    }
    for index in range(200, len(five)):
        current = five.iloc[index]
        counts["bars_checked_after_warmup"] += 1
        close_time = int(current["timestamp"]) + TIMEFRAME_MS["5m"]
        eligible = fifteen[
            fifteen["timestamp"] + TIMEFRAME_MS["15m"] <= close_time
        ]
        fields = ["ema20", "ema200", "rsi", "macd", "macd_signal",
                  "volume_sma20", "atr"]
        if eligible.empty or current[fields].isna().any():
            continue
        trend = eligible.iloc[-1]
        if trend[["ema20", "ema200"]].isna().any():
            continue
        counts["bars_with_valid_indicators"] += 1
        bullish = trend["ema20"] > trend["ema200"]
        if bullish:
            counts["bullish_15m_trend_bars"] += 1
        conditions = [
            current["ema20"] > current["ema200"],
            current["rsi"] > 50,
            current["macd"] > current["macd_signal"],
            current["volume"] > current["volume_sma20"],
            current["close"] > current["ema20"],
        ]
        names = list(counts["condition_pass_counts"])
        for name, passed in zip(names, conditions):
            if passed:
                counts["condition_pass_counts"][name] += 1
        if sum(conditions) >= 4:
            counts["bars_with_at_least_4_of_5_5m_conditions"] += 1
        if sum(conditions) >= 4 and bullish and current["atr"] > 0:
            counts["actual_buy_signal_bars"] += 1
    return counts


def research_symbol(exchange, symbol):
    five = calculate_indicators(fetch_history(exchange, symbol, "5m"))
    fifteen = calculate_indicators(fetch_history(exchange, symbol, "15m"))
    split = int(len(five) * 0.70)
    if split <= 200 or len(five) - split < 30:
        raise RuntimeError(f"Datos insuficientes para dividir train/test en {symbol}")

    configurations = []
    for stop_mult in STOP_MULTIPLIERS:
        for reward_ratio in REWARD_RATIOS:
            train = simulate(five, fifteen, stop_mult, reward_ratio, 200, split)
            test = simulate(five, fifteen, stop_mult, reward_ratio, split, len(five))
            configurations.append({
                "stop_atr": stop_mult,
                "reward_risk": reward_ratio,
                "train": {k: v for k, v in train.items() if k != "trade_log"},
                "out_of_sample": {k: v for k, v in test.items() if k != "trade_log"},
            })

    eligible = [c for c in configurations if c["train"]["trades"] >= 5]
    selected = max(
        eligible,
        key=lambda c: (c["train"]["net_pnl_usdt"], c["train"]["profit_factor"] or 0),
        default=None,
    )
    baseline = next(c for c in configurations
                    if c["stop_atr"] == 1.2 and c["reward_risk"] == 2.0)
    return {
        "symbol": symbol,
        "five_minute_closed_candles": len(five),
        "fifteen_minute_closed_candles": len(fifteen),
        "train_bars": split - 200,
        "out_of_sample_bars": len(five) - split,
        "signal_diagnostics": signal_diagnostics(five, fifteen),
        "baseline_1_2_atr_2r": baseline,
        "selected_on_train_only": selected,
        "all_configurations": configurations,
        "warning": "Recent Kraken OHLC history is limited; this is a short research sample, not proof of an edge.",
    }


def main():
    exchange = ccxt.kraken({"enableRateLimit": True})
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "research_only_no_orders_no_paper_state_changes",
        "fee_rate_per_side": FEE_RATE,
        "risk_fraction_per_trade": RISK_FRACTION,
        "max_position_fraction": MAX_POSITION_FRACTION,
        "data_limit_per_timeframe": CANDLE_LIMIT,
        "symbols": {},
    }
    for symbol in SYMBOLS:
        try:
            report["symbols"][symbol] = research_symbol(exchange, symbol)
        except Exception as error:
            report["symbols"][symbol] = {"error": str(error)}
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "generated_at": report["generated_at"],
        "symbols": {
            symbol: {
                "error": data.get("error"),
                "bars_5m": data.get("five_minute_closed_candles"),
                "signal_diagnostics": data.get("signal_diagnostics"),
                "baseline_train": data.get("baseline_1_2_atr_2r", {}).get("train"),
                "baseline_test": data.get("baseline_1_2_atr_2r", {}).get("out_of_sample"),
                "selected_config": (
                    {k: data["selected_on_train_only"][k]
                     for k in ("stop_atr", "reward_risk")}
                    if data.get("selected_on_train_only") else None
                ),
            }
            for symbol, data in report["symbols"].items()
        },
        "report_file": str(OUTPUT),
    }, indent=2))


if __name__ == "__main__":
    main()
