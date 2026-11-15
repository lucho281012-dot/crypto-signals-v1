import unittest

from historical_oos_validation import backtest_out_of_sample
from historical_segment_backtest import generate_segment_signals


def rising(count, interval, first=0):
    rows = []
    for i in range(count):
        close = 100 + i * 0.2
        rows.append({
            "timestamp": first + i * interval,
            "open": close - 0.05,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100 + i,
        })
    return rows


class OutOfSampleTests(unittest.TestCase):
    def test_signals_start_only_after_chronological_split(self):
        five = rising(900, 300_000)
        fifteen = rising(300, 900_000)
        split = int(len(five) * 0.70)
        signals = generate_segment_signals(five, fifteen, start_index=split)
        self.assertTrue(signals)
        self.assertTrue(all(s["timestamp"] >= five[split]["timestamp"] for s in signals))

    def test_metrics_are_test_only_and_segments_are_independent(self):
        segments = [{
            "candles_5m": rising(900, 300_000),
            "candles_15m": rising(300, 900_000),
        }]
        result = backtest_out_of_sample(segments)
        self.assertEqual(result["segment_count"], 1)
        self.assertEqual(result["initial_balance_sum_of_independent_segments"], 100.0)
        self.assertTrue(result["test_only_trades"])
        self.assertFalse(result["portfolio_compounded_across_gaps"])
        self.assertEqual(result["segment_results"][0]["train_5m_rows"], 630)
        self.assertEqual(
            result["segment_results"][0]["test_first_5m_timestamp"],
            segments[0]["candles_5m"][630]["timestamp"],
        )

    def test_rejects_invalid_split(self):
        with self.assertRaises(ValueError):
            backtest_out_of_sample([], train_fraction=0.95)


if __name__ == "__main__":
    unittest.main()
