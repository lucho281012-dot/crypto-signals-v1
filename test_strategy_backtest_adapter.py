import copy
import unittest

from strategy_backtest_adapter import generate_closed_candle_signal


def rising_candles(count, interval_ms, first_timestamp):
    rows = []
    for index in range(count):
        close = 100.0 + index * 0.15
        rows.append({
            "timestamp": first_timestamp + index * interval_ms,
            "open": close - 0.05,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0 + index,
        })
    return rows


def aligned_series():
    # Last 5m candle closes exactly when the latest 15m candle closes.
    five = rising_candles(220, 300_000, 600_000)
    five_close = five[-1]["timestamp"] + 300_000
    last_fifteen_open = five_close - 900_000
    fifteen = rising_candles(220, 900_000,
                             last_fifteen_open - 219 * 900_000)
    return five, fifteen


class ClosedCandleAdapterTests(unittest.TestCase):
    def test_generates_signal_from_last_closed_candle(self):
        five, fifteen = aligned_series()
        signal = generate_closed_candle_signal(five, fifteen)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        self.assertEqual(signal["timestamp"], five[-1]["timestamp"])
        self.assertEqual(signal["source_15m_timestamp"], fifteen[-1]["timestamp"])
        self.assertGreater(signal["atr"], 0)

    def test_does_not_mutate_input_candles(self):
        five, fifteen = aligned_series()
        original_five = copy.deepcopy(five)
        original_fifteen = copy.deepcopy(fifteen)
        generate_closed_candle_signal(five, fifteen)
        self.assertEqual(five, original_five)
        self.assertEqual(fifteen, original_fifteen)

    def test_rejects_gaps_instead_of_fabricating_candles(self):
        five, fifteen = aligned_series()
        del five[100]
        with self.assertRaisesRegex(ValueError, "huecos"):
            generate_closed_candle_signal(five, fifteen)

    def test_rejects_stale_or_misaligned_15m_data(self):
        five, fifteen = aligned_series()
        fifteen[-1]["timestamp"] -= 900_000
        with self.assertRaisesRegex(ValueError, "15m"):
            generate_closed_candle_signal(five, fifteen)

    def test_rejects_insufficient_history(self):
        five, fifteen = aligned_series()
        with self.assertRaisesRegex(ValueError, "200 velas"):
            generate_closed_candle_signal(five[-199:], fifteen)


if __name__ == "__main__":
    unittest.main()
