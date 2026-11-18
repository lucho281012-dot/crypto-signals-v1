"""Crypto Signals V2 research-only signal engine.

No exchange order methods, credentials, network calls, or paper-state writes.
Input candles are closed OHLCV rows with millisecond UTC timestamps.
"""
from __future__ import annotations

import math

import pandas as pd

INTERVAL_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
FEE_RATE = 0.001
RISK_FRACTION = 0.01
MAX_GROSS_EXPOSURE = 0.95
MAX_OPEN_POSITIONS = 3
STOP_ATR_MULTIPLIER = 1.5
REWARD_RISK = 2.0


def _validate_candles(candles: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required.difference(candles.columns)
    if missing:
        raise ValueError(f"Missing candle columns: {sorted(missing)}")
    frame = candles.copy()
    frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="raise").astype("int64")
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    for name in ("open", "high", "low", "close", "volume"):
        frame[name] = pd.to_numeric(frame[name], errors="raise")
    if frame[list(required)].isna().any().any():
        raise ValueError("OHLCV candles contain null values")
    numeric_columns = ["open", "high", "low", "close", "volume"]
    if not all(math.isfinite(float(value)) for value in frame[numeric_columns].to_numpy().ravel()):
        raise ValueError("OHLCV candles contain non-finite values")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (frame["volume"] < 0).any():
        raise ValueError("Volume cannot be negative")
    invalid = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        raise ValueError("Invalid OHLC range")
    return frame


def calculate_indicators(candles: pd.DataFrame) -> pd.DataFrame:
    """Calculate EMA, RSI, MACD, ATR, ADX and volume baseline."""
    df = _validate_candles(candles)
    close, high, low = df["close"], df["high"], df["low"]
    df["ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    df["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    df["ema200"] = close.ewm(span=200, adjust=False, min_periods=200).mean()

    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    df["rsi"] = 100 - 100 / (1 + rs)

    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    df["macd"] = macd
    df["macd_signal"] = macd.ewm(span=9, adjust=False).mean()
    df["volume_sma20"] = df["volume"].rolling(20, min_periods=20).mean()

    previous_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_safe = df["atr"].replace(0, float("nan"))
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr_safe
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["atr_percent"] = df["atr"] / close
    return df


def resample_ohlcv(candles: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate lower timeframe candles; only complete buckets are returned."""
    if timeframe not in ("1h", "4h"):
        raise ValueError("Only 1h and 4h resampling is supported")
    base = _validate_candles(candles)
    interval = INTERVAL_MS[timeframe]
    indexed = base.set_index(pd.to_datetime(base["timestamp"], unit="ms", utc=True))
    result = indexed.resample(timeframe, origin="epoch", label="left", closed="left").agg(
        {"timestamp": "first", "open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    )
    counts = indexed["close"].resample(timeframe, origin="epoch", label="left", closed="left").count()
    expected = interval // INTERVAL_MS["15m"]
    result = result[counts == expected].dropna(subset=["open", "high", "low", "close"])
    result["timestamp"] = result.index.astype("int64") // 1_000_000
    return result.reset_index(drop=True)[["timestamp", "open", "high", "low", "close", "volume"]]


def latest_completed_row(indicators: pd.DataFrame, signal_candle_timestamp: int,
                         timeframe: str) -> pd.Series | None:
    """Return a higher-timeframe row only if its close <= signal candle close."""
    if timeframe not in INTERVAL_MS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    if indicators.empty:
        return None
    signal_close = int(signal_candle_timestamp) + INTERVAL_MS["5m"]
    completed = indicators[
        indicators["timestamp"].astype("int64") + INTERVAL_MS[timeframe] <= signal_close
    ]
    return None if completed.empty else completed.iloc[-1]


def evaluate_buy_signal_at(frames: dict, index: int = -1) -> dict | None:
    """Evaluate one signal from precomputed indicator frames.

    This is the single source of truth shared by live-style analysis and backtests.
    The caller must provide closed candles and indicator frames for all timeframes.
    """
    five = frames["5m"]
    if five.empty:
        return None
    current = five.iloc[index]
    fields = ["ema20", "ema50", "ema200", "rsi", "macd", "macd_signal",
              "volume_sma20", "atr", "adx", "atr_percent"]
    if current[fields].isna().any():
        return None

    higher = {
        tf: latest_completed_row(frames[tf], int(current["timestamp"]), tf)
        for tf in ("15m", "1h", "4h")
    }
    if any(row is None for row in higher.values()):
        return None
    required_fields = {
        "15m": ["ema20", "ema50", "adx"],
        "1h": ["ema50", "ema200", "adx"],
        "4h": ["ema20", "ema50", "adx"],
    }
    if any(higher[tf][fields].isna().any() for tf, fields in required_fields.items()):
        return None

    if not (higher["4h"]["ema20"] > higher["4h"]["ema50"]
            and higher["1h"]["ema50"] > higher["1h"]["ema200"]
            and higher["15m"]["ema20"] > higher["15m"]["ema50"]):
        return None
    if min(float(higher[tf]["adx"]) for tf in ("1h", "4h")) < 18:
        return None
    if not 0.001 <= float(current["atr_percent"]) <= 0.025:
        return None

    conditions = [
        current["ema20"] > current["ema50"],
        current["close"] > current["ema20"],
        52 <= current["rsi"] <= 70,
        current["macd"] > current["macd_signal"],
        current["volume"] > current["volume_sma20"],
    ]
    atr = float(current["atr"])
    passed = sum(bool(value) for value in conditions)
    if passed < 4 or atr <= 0:
        return None

    entry = float(current["close"])
    stop = entry - STOP_ATR_MULTIPLIER * atr
    if stop <= 0 or stop >= entry:
        return None
    target = entry + REWARD_RISK * (entry - stop)
    return {
        "side": "BUY",
        "timestamp": int(current["timestamp"]),
        "entry_reference": entry,
        "stop": stop,
        "target": target,
        "atr": atr,
        "conditions_passed": passed,
        "regime": "bullish_trending",
        "strategy": "crypto-signals-v2",
    }


def generate_buy_signal(candles_5m: pd.DataFrame, candles_15m: pd.DataFrame,
                        candles_1h: pd.DataFrame, candles_4h: pd.DataFrame) -> dict | None:
    """Calculate indicators and evaluate the latest closed 5m candle."""
    frames = {
        "5m": calculate_indicators(candles_5m),
        "15m": calculate_indicators(candles_15m),
        "1h": calculate_indicators(candles_1h),
        "4h": calculate_indicators(candles_4h),
    }
    if len(frames["5m"]) < 200:
        return None
    return evaluate_buy_signal_at(frames)

def calculate_position_size(equity: float, cash: float, gross_exposure: float,
                            entry: float, stop: float, open_positions: int = 0) -> dict:
    """Fee-aware sizing with 1% risk, 95% gross exposure and max 3 positions."""
    values = (equity, cash, gross_exposure, entry, stop)
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError("Sizing inputs must be finite numbers")
    if equity <= 0 or cash <= 0 or gross_exposure < 0 or open_positions < 0 or entry <= stop or stop <= 0:
        return {"quantity": 0.0, "investment": 0.0, "risk_usdt": 0.0,
                "reason": "invalid_or_insufficient_balance"}
    if open_positions >= MAX_OPEN_POSITIONS:
        return {"quantity": 0.0, "investment": 0.0, "risk_usdt": 0.0,
                "reason": "max_open_positions"}
    remaining_exposure = max(0.0, equity * MAX_GROSS_EXPOSURE - gross_exposure)
    risk_per_unit = entry - stop + entry * FEE_RATE + stop * FEE_RATE
    by_risk = equity * RISK_FRACTION / risk_per_unit
    by_cash = cash / (entry * (1 + FEE_RATE))
    by_exposure = remaining_exposure / (entry * (1 + FEE_RATE))
    quantity = max(0.0, min(by_risk, by_cash, by_exposure))
    investment = quantity * entry
    risk = quantity * risk_per_unit
    reason = "ok" if quantity > 0 else "exposure_or_cash_limit"
    return {"quantity": quantity, "investment": investment, "risk_usdt": risk,
            "reason": reason}
