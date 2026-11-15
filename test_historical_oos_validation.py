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
        self.assertTrue(all(s["conditions_met"] in (4, 5) for s in signals))

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
        self.assertEqual(
            sum(result["exit_reason_counts"].values()), result["trade_count"]
        )
        self.assertEqual(
            result["wins"] + result["losses"] + result["breakeven_count"],
            result["trade_count"],
        )
        self.assertIsNotNone(result["mean_trade_net_pnl"])
        self.assertIsNotNone(result["median_holding_minutes"])
        self.assertEqual(
            sum(result["signal_condition_counts"].values()),
            sum(row["test_signal_count"] for row in result["segment_results"]),
        )
        self.assertEqual(
            sum(row["executed_trades"] for row in result["trade_results_by_condition_count"].values()),
            result["trade_count"],
        )
        self.assertTrue(
            set(result["trade_results_by_condition_count"]).issubset({"4", "5"})
        )

    def test_empty_trade_diagnostics_are_explicit(self):
        result = backtest_out_of_sample([])
        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(result["exit_reason_counts"], {})
        self.assertEqual(result["signal_condition_counts"], {})
        self.assertEqual(result["trade_results_by_condition_count"], {})
        self.assertIsNone(result["mean_trade_net_pnl"])
        self.assertIsNone(result["median_holding_minutes"])

    def test_rejects_invalid_split(self):
        with self.assertRaises(ValueError):
            backtest_out_of_sample([], train_fraction=0.95)


if __name__ == "__main__":
    unittest.main()
