
import math


def evaluate_signal(data):
    required = ["close", "ema_50", "rsi_14", "atr_14"]

    for key in required:
        if key not in data:
            raise ValueError(f"Missing indicator: {key}")

        if not math.isfinite(float(data[key])):
            raise ValueError(f"Invalid indicator: {key}")

    close = float(data["close"])
    ema = float(data["ema_50"])
    rsi = float(data["rsi_14"])
    atr = float(data["atr_14"])

    if close <= 0 or ema <= 0:
        raise ValueError("Invalid price or EMA")

    if not 0 <= rsi <= 100 or atr <= 0:
        raise ValueError("Invalid RSI or ATR")

    signal = "WAIT"
    reasons = []

    if close > ema and 55 <= rsi <= 70:
        signal = "BUY"
        reasons.append("Price above EMA 50")
        reasons.append("RSI confirms bullish momentum")

    elif close < ema and 30 <= rsi <= 45:
        signal = "SELL"
        reasons.append("Price below EMA 50")
        reasons.append("RSI confirms bearish momentum")

    else:
        reasons.append("Conditions do not confirm an entry")

    return {
        "signal": signal,
        "close": close,
        "ema_50": ema,
        "rsi_14": rsi,
        "atr_14": atr,
        "reasons": reasons,
        "execution": "DISABLED",
        "mode": "PAPER_ANALYSIS"
    }
