import unittest

import pandas as pd

from strategy_v2 import (
    INTERVAL_MS,
    calculate_indicators,
    calculate_position_size,
    latest_completed_row,
    resample_ohlcv,
)


def candles(count, interval_ms=INTERVAL_MS["15m"], start=0):
    rows = []
    price = 100.0
    for index in range(count):
        # Deterministic gentle uptrend with a small oscillation.
        close = price + 0.08 + (0.03 if index % 3 == 0 else -0.01)
        rows.append({
            "timestamp": start + index * interval_ms,
            "open": price,
            "high": max(price, close) + 0.2,
            "low": min(price, close) - 0.2,
            "close": close,
            "volume": 10.0 + (index % 5),
        })
        price = close
    return pd.DataFrame(rows)


class StrategyV2Tests(unittest.TestCase):
    def test_resample_returns_only_complete_buckets(self):
        source = candles(9)
        hourly = resample_ohlcv(source, "1h")
        self.assertEqual(len(hourly), 2)
        self.assertEqual(hourly.iloc[0]["volume"], sum(source.iloc[:4]["volume"]))
        four_hour = resample_ohlcv(candles(17), "4h")
        self.assertEqual(len(four_hour), 1)

    def test_higher_timeframe_row_must_be_fully_closed(self):
        frame = pd.DataFrame([
            {"timestamp": 0, "ema20": 10.0},
            {"timestamp": INTERVAL_MS["1h"], "ema20": 11.0},
        ])
        # 5m candle at 55m closes at 60m: the 1h candle starting at 60m is not closed.
        row = latest_completed_row(frame, 55 * 60_000, "1h")
        self.assertEqual(int(row["timestamp"]), 0)

    def test_indicator_calculation_is_causal(self):
        source = candles(260, INTERVAL_MS["5m"])
        full = calculate_indicators(source)
        prefix = calculate_indicators(source.iloc[:240])
        self.assertAlmostEqual(full.iloc[239]["ema50"], prefix.iloc[-1]["ema50"])
        self.assertAlmostEqual(full.iloc[239]["rsi"], prefix.iloc[-1]["rsi"])

    def test_risk_and_exposure_caps_are_respected(self):
        result = calculate_position_size(
            equity=100.0, cash=100.0, gross_exposure=0.0,
            entry=100.0, stop=98.0, open_positions=0,
        )
        self.assertGreater(result["quantity"], 0)
        self.assertLessEqual(result["risk_usdt"], 1.0 + 1e-9)
        self.assertLessEqual(
            result["investment"] * 1.001, 95.0 + 1e-9
        )

    def test_no_new_position_when_exposure_is_exhausted(self):
        result = calculate_position_size(
            equity=100.0, cash=10.0, gross_exposure=95.0,
            entry=100.0, stop=98.0, open_positions=1,
        )
        self.assertEqual(result["quantity"], 0.0)
        self.assertEqual(result["reason"], "exposure_or_cash_limit")

    def test_maximum_open_position_count_is_enforced(self):
        result = calculate_position_size(
            equity=100.0, cash=100.0, gross_exposure=0.0,
            entry=100.0, stop=98.0, open_positions=3,
        )
        self.assertEqual(result["quantity"], 0.0)
        self.assertEqual(result["reason"], "max_open_positions")

    def test_invalid_ohlc_is_rejected(self):
        source = candles(10)
        source.loc[0, "high"] = 1.0
        with self.assertRaisesRegex(ValueError, "Invalid OHLC"):
            calculate_indicators(source)


if __name__ == "__main__":
    unittest.main()
