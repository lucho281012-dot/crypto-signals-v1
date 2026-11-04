
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

    # Excluimos la vela todavía abierta.
    current = df5.iloc[-2]
    trend = df15.iloc[-2]

    if current.isna().any() or trend.isna().any():
        return None

    conditions = [
        current["ema20"] > current["ema200"],
        current["rsi"] > 50,
        current["macd"] > current["macd_signal"],
        current["volume"] > current["volume_sma20"],
        current["close"] > current["ema20"]
    ]

    bullish_trend = trend["ema20"] > trend["ema200"]

    if sum(conditions) >= 4 and bullish_trend:
        entry = float(current["close"])
        atr = float(current["atr"])

        if atr <= 0:
            return None

        stop = entry - (1.2 * atr)
        target = entry + (2 * (entry - stop))

        return {
            "side": "BUY",
            "entry": entry,
            "stop": stop,
            "target": target,
            "rsi": float(current["rsi"]),
            "atr": atr,
            "conditions_met": sum(conditions)
        }

    return None


if __name__ == "__main__":
    print("Crypto Signals Spot Engine listo.")
