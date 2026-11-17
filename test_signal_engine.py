import unittest
from unittest.mock import patch

import pandas as pd

import signal_engine as se


def indicator_frame(last):
    row = {
        "ema20": 110.0,
        "ema200": 100.0,
        "rsi": 60.0,
        "macd": 2.0,
        "macd_signal": 1.0,
        "volume": 150.0,
        "volume_sma20": 100.0,
        "close": 111.0,
        "atr": 2.0,
    }
    rows = [row.copy() for _ in range(3)]
    rows[-2].update(last)
    return pd.DataFrame(rows)


class SignalEngineTests(unittest.TestCase):
    def test_buy_signal_when_four_of_five_filters_and_trend_confirm(self):
        five = indicator_frame({})
        fifteen = indicator_frame({})
        with patch.object(se, "calculate_indicators", side_effect=[five, fifteen]):
            signal = se.analyze_spot([{}] * 200, [{}] * 200)
        self.assertEqual(signal["side"], "BUY")
        self.assertAlmostEqual(signal["stop"], signal["entry"] - 2.4)
        self.assertAlmostEqual(signal["target"], signal["entry"] + 4.8)
        self.assertEqual(signal["conditions_met"], 5)

    def test_no_signal_when_fewer_than_four_filters_pass(self):
        five = indicator_frame({"rsi": 45.0, "macd": 0.0, "volume": 50.0})
        fifteen = indicator_frame({})
        with patch.object(se, "calculate_indicators", side_effect=[five, fifteen]):
            signal = se.analyze_spot([{}] * 200, [{}] * 200)
        self.assertIsNone(signal)

    def test_no_signal_without_bullish_15m_trend(self):
        five = indicator_frame({})
        fifteen = indicator_frame({"ema20": 90.0, "ema200": 100.0})
        with patch.object(se, "calculate_indicators", side_effect=[five, fifteen]):
            signal = se.analyze_spot([{}] * 200, [{}] * 200)
        self.assertIsNone(signal)

    def test_open_candle_is_not_used(self):
        five = indicator_frame({})
        five.iloc[-1, five.columns.get_loc("ema20")] = 1.0
        fifteen = indicator_frame({})
        with patch.object(se, "calculate_indicators", side_effect=[five, fifteen]):
            signal = se.analyze_spot([{}] * 200, [{}] * 200)
        self.assertIsNotNone(signal)


if __name__ == "__main__":
    unittest.main()
