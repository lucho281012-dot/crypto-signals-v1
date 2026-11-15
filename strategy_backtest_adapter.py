"""Leakage-safe adapter from closed 5m/15m candles to backtest signals.

Input timestamps are candle OPEN times in UTC milliseconds (CCXT format).
No data is fetched, filled, resampled, or written by this module.
"""
from copy import deepcopy

from signal_engine import analyze_spot

FIVE_MINUTES_MS = 5 * 60 * 1000
FIFTEEN_MINUTES_MS = 15 * 60 * 1000
_REQUIRED = ("timestamp", "open", "high", "low", "close", "volume")


def _validate_closed_candles(candles, interval_ms, label):
    if len(candles) < 200:
        raise ValueError(f"{label}: se requieren al menos 200 velas cerradas")

    previous = None
    for index, candle in enumerate(candles):
        missing = [key for key in _REQUIRED if key not in candle]
        if missing:
            raise ValueError(f"{label}: vela {index} sin campos {missing}")

        timestamp = int(candle["timestamp"])
        if timestamp % interval_ms:
            raise ValueError(f"{label}: timestamp fuera de alineación")
        if previous is not None and timestamp - previous != interval_ms:
            raise ValueError(f"{label}: hay huecos, duplicados o desorden temporal")
        previous = timestamp

    return int(candles[-1]["timestamp"])


def generate_closed_candle_signal(candles_5m_closed, candles_15m_closed):
    """Return one backtest BUY signal or None, using only fully closed bars.

    The production signal engine intentionally reads iloc[-2] because live
    feeds include a forming candle. We append a private duplicate sentinel so
    its [-2] selection refers to the final supplied CLOSED candle. The sentinel
    cannot affect indicators at [-2] because all indicators are causal.
    """
    last_5m_open = _validate_closed_candles(
        candles_5m_closed, FIVE_MINUTES_MS, "5m"
    )
    last_15m_open = _validate_closed_candles(
        candles_15m_closed, FIFTEEN_MINUTES_MS, "15m"
    )

    five_minute_close = last_5m_open + FIVE_MINUTES_MS
    expected_15m_open = (
        (five_minute_close // FIFTEEN_MINUTES_MS) * FIFTEEN_MINUTES_MS
        - FIFTEEN_MINUTES_MS
    )
    if last_15m_open != expected_15m_open:
        raise ValueError(
            "15m desalineado: se exige la última vela 15m cerrada "
            "disponible al cierre de la última vela 5m"
        )

    # Deep copies prevent the signal engine or caller from sharing mutable rows.
    five = deepcopy(candles_5m_closed)
    fifteen = deepcopy(candles_15m_closed)
    five.append(deepcopy(five[-1]))
    fifteen.append(deepcopy(fifteen[-1]))

    signal = analyze_spot(five, fifteen)
    if signal is None:
        return None

    if signal.get("side") != "BUY":
        return None

    return {
        "timestamp": last_5m_open,
        "side": "BUY",
        "atr": float(signal["atr"]),
        "signal_close": float(signal["entry"]),
        "stop": float(signal["stop"]),
        "target": float(signal["target"]),
        "conditions_met": int(signal["conditions_met"]),
        "source_5m_timestamp": last_5m_open,
        "source_15m_timestamp": last_15m_open,
    }
