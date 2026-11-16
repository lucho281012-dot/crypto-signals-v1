import unittest

from historical_5of5_walk_forward import backtest_5of5_walk_forward


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


class FiveOfFiveWalkForwardTests(unittest.TestCase):
    def test_four_disjoint_chronological_folds_are_independent(self):
        segment = {
            "candles_5m": rising(800, 300_000),
            "candles_15m": rising(267, 900_000),
        }
        result = backtest_5of5_walk_forward([segment])
        self.assertEqual(result["fold_count"], 4)
        self.assertEqual(result["segments_evaluated"], 1)
        self.assertTrue(result["folds_are_non_overlapping"])
        self.assertFalse(result["capital_and_positions_carried_between_folds"])
        self.assertTrue(result["test_only_trades"])
        self.assertEqual(
            result["initial_balance_sum_of_independent_folds"], 400.0
        )
        self.assertEqual(
            result["trade_count"], result["wins"] + result["losses"]
        )
        folds = result["folds"]
        self.assertEqual([f["fold_index"] for f in folds], [1, 2, 3, 4])
        for previous, current in zip(folds, folds[1:]):
            self.assertEqual(previous["test_last_timestamp"] + 300_000,
                             current["test_first_timestamp"])
        self.assertTrue(all(f["test_5m_rows"] >= 50 for f in folds))
        self.assertTrue(all(
            f["test_start_fraction"] < f["test_end_fraction"] for f in folds
        ))

    def test_short_segments_are_reported_as_excluded(self):
        segment = {
            "candles_5m": rising(399, 300_000),
            "candles_15m": rising(133, 900_000),
        }
        result = backtest_5of5_walk_forward([segment])
        self.assertEqual(result["fold_count"], 0)
        self.assertEqual(result["segments_excluded_short"], 1)
        self.assertEqual(result["excluded_segments"][0]["segment_index"], 0)
        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(result["equal_allocation_return_percent"], 0.0)

    def test_rejects_non_positive_initial_balance(self):
        with self.assertRaises(ValueError):
            backtest_5of5_walk_forward([], initial_balance=0)


if __name__ == "__main__":
    unittest.main()
