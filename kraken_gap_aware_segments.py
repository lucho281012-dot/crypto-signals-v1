"""Gap-aware pairing of real Kraken 5m and 15m candles.

No candle is synthesized, forward-filled, resampled, or bridged across a gap.
Each returned segment is safe to pass to the closed-candle strategy adapter.
"""
from __future__ import annotations

FIVE_MINUTES_MS = 5 * 60 * 1000
FIFTEEN_MINUTES_MS = 15 * 60 * 1000


def _validate_series(candles, interval_ms, label):
    previous = None
    for index, candle in enumerate(candles):
        if "timestamp" not in candle:
            raise ValueError(f"{label}: vela {index} sin timestamp")
        timestamp = int(candle["timestamp"])
        if timestamp < 0 or timestamp % interval_ms:
            raise ValueError(f"{label}: timestamp fuera de alineación")
        if previous is not None and timestamp <= previous:
            raise ValueError(f"{label}: timestamps duplicados o desordenados")
        previous = timestamp


def build_aligned_contiguous_segments(
    candles_5m,
    candles_15m,
    min_5m_candles=200,
    min_15m_candles=200,
):
    """Return paired, maximal continuous 5m/15m segments.

    For each 5m candle, the paired 15m candle is the latest fully closed
    15m candle available at that 5m candle's close. A segment is broken by
    any missing 5m bar, missing required 15m bar, or discontinuity in the
    selected 15m sequence.

    Each output segment has at least the requested number of candles in both
    timeframes. The 15m rows are unique and strictly contiguous; 5m rows are
    strictly contiguous. Original candle dictionaries are copied.
    """
    if isinstance(min_5m_candles, bool) or int(min_5m_candles) < 2:
        raise ValueError("min_5m_candles debe ser al menos 2")
    if isinstance(min_15m_candles, bool) or int(min_15m_candles) < 2:
        raise ValueError("min_15m_candles debe ser al menos 2")
    min_5m_candles = int(min_5m_candles)
    min_15m_candles = int(min_15m_candles)

    _validate_series(candles_5m, FIVE_MINUTES_MS, "5m")
    _validate_series(candles_15m, FIFTEEN_MINUTES_MS, "15m")

    fifteen_by_timestamp = {
        int(candle["timestamp"]): candle for candle in candles_15m
    }
    completed = []
    current_5m = []
    current_15m = []
    last_5m_timestamp = None
    last_selected_15m_timestamp = None
    skipped_5m_without_15m = 0
    breaks_5m = 0
    breaks_15m = 0

    def finish_segment():
        nonlocal current_5m, current_15m
        if (len(current_5m) >= min_5m_candles
                and len(current_15m) >= min_15m_candles):
            completed.append({
                "candles_5m": current_5m,
                "candles_15m": current_15m,
                "metadata": {
                    "five_minute_rows": len(current_5m),
                    "fifteen_minute_rows": len(current_15m),
                    "first_5m_timestamp": current_5m[0]["timestamp"],
                    "last_5m_timestamp": current_5m[-1]["timestamp"],
                    "first_15m_timestamp": current_15m[0]["timestamp"],
                    "last_15m_timestamp": current_15m[-1]["timestamp"],
                },
            })
        current_5m = []
        current_15m = []

    for candle_5m in candles_5m:
        timestamp_5m = int(candle_5m["timestamp"])
        close_time_5m = timestamp_5m + FIVE_MINUTES_MS
        selected_15m_timestamp = (
            (close_time_5m // FIFTEEN_MINUTES_MS) * FIFTEEN_MINUTES_MS
            - FIFTEEN_MINUTES_MS
        )
        candle_15m = fifteen_by_timestamp.get(selected_15m_timestamp)

        if candle_15m is None:
            skipped_5m_without_15m += 1
            if current_5m:
                finish_segment()
            last_5m_timestamp = None
            last_selected_15m_timestamp = None
            continue

        if last_5m_timestamp is not None:
            if timestamp_5m - last_5m_timestamp != FIVE_MINUTES_MS:
                breaks_5m += 1
                finish_segment()
                last_selected_15m_timestamp = None

        if last_selected_15m_timestamp is not None:
            delta_15m = selected_15m_timestamp - last_selected_15m_timestamp
            if delta_15m not in (0, FIFTEEN_MINUTES_MS):
                breaks_15m += 1
                finish_segment()
                last_selected_15m_timestamp = None

        current_5m.append(dict(candle_5m))
        if selected_15m_timestamp != last_selected_15m_timestamp:
            current_15m.append(dict(candle_15m))
        last_5m_timestamp = timestamp_5m
        last_selected_15m_timestamp = selected_15m_timestamp

    if current_5m:
        finish_segment()

    return {
        "segments": completed,
        "metadata": {
            "input_5m_rows": len(candles_5m),
            "input_15m_rows": len(candles_15m),
            "usable_segments": len(completed),
            "usable_5m_rows": sum(len(s["candles_5m"]) for s in completed),
            "usable_15m_rows": sum(len(s["candles_15m"]) for s in completed),
            "skipped_5m_without_matching_15m": skipped_5m_without_15m,
            "five_minute_discontinuities": breaks_5m,
            "fifteen_minute_discontinuities": breaks_15m,
            "min_5m_candles": min_5m_candles,
            "min_15m_candles": min_15m_candles,
            "candles_fabricated": 0,
            "gaps_filled": False,
        },
    }
