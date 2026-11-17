import pandas as pd


def calculate_indicators(candles):
    df = pd.DataFrame(candles)

    if len(df) < 200:
        return None

    close = df["close"]
    volume = df["volume"]

    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema200"] = close.ewm(span=200, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14, adjust=False, min_periods=14
    ).mean()
    avg_loss = loss.ewm(
        alpha=1/14, adjust=False, min_periods=14
    ).mean()

    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(
        span=9, adjust=False
    ).mean()

    df["volume_sma20"] = volume.rolling(20).mean()

    previous_close = close.shift(1)
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs()
    ], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(14).mean()

    return df


def analyze_spot(candles_5m, candles_15m):
    df5 = calculate_indicators(candles_5m)
    df15 = calculate_indicators(candles_15m)

    if df5 is None or df15 is None:
        return None

    # Excluimos la vela todavía abierta: la señal se calcula con [-2].
    current = df5.iloc[-2]
    trend = df15.iloc[-2]

    if current.isna().any() or trend.isna().any():
        return None

    condition_values = {
        "ema20_above_ema200": bool(current["ema20"] > current["ema200"]),
        "rsi_above_50": bool(current["rsi"] > 50),
        "macd_above_signal": bool(current["macd"] > current["macd_signal"]),
        "volume_above_sma20": bool(current["volume"] > current["volume_sma20"]),
        "close_above_ema20": bool(current["close"] > current["ema20"]),
    }
    conditions_met = sum(condition_values.values())
    bullish_trend = bool(trend["ema20"] > trend["ema200"])

    # No se modifican los filtros, umbrales ni la decisión de la estrategia.
    if conditions_met >= 4 and bullish_trend:
        entry = float(current["close"])
        atr = float(current["atr"])

        if atr <= 0:
            return None

        stop = entry - (1.2 * atr)
        target = entry + (2 * (entry - stop))

        diagnostic = {
            "schema_version": 1,
            "strategy": "spot_v1",
            "decision": "BUY",
            "signal_timeframes": {"entry": "5m", "trend": "15m"},
            "signal_candle_timestamp_5m": int(candles_5m[-2]["timestamp"]),
            "trend_candle_timestamp_15m": int(candles_15m[-2]["timestamp"]),
            "conditions": condition_values,
            "conditions_met": int(conditions_met),
            "required_conditions": 4,
            "bullish_trend_15m": bullish_trend,
            "indicators_5m": {
                "close": float(current["close"]),
                "ema20": float(current["ema20"]),
                "ema200": float(current["ema200"]),
                "rsi14": float(current["rsi"]),
                "macd": float(current["macd"]),
                "macd_signal": float(current["macd_signal"]),
                "volume": float(current["volume"]),
                "volume_sma20": float(current["volume_sma20"]),
                "atr14": atr,
            },
            "indicators_15m": {
                "close": float(trend["close"]),
                "ema20": float(trend["ema20"]),
                "ema200": float(trend["ema200"]),
            },
        }

        return {
            "side": "BUY",
            "entry": entry,
            "stop": stop,
            "target": target,
            "rsi": float(current["rsi"]),
            "atr": atr,
            "conditions_met": int(conditions_met),
            "signal_diagnostic": diagnostic,
        }

    return None


if __name__ == "__main__":
    print("Crypto Signals Spot Engine listo.")
