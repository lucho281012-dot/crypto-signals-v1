import unittest

from historical_entry_filter_comparison import (
    FILTERS, aggregate_entry_filter_folds, compare_entry_filters,
)


def candles(count=8):
    rows = []
    for i in range(count):
        close = 100.0 + i * 0.1
        rows.append({
            "timestamp": i * 300_000,
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 100.0,
        })
    return rows


def signal(index, rsi=58.0, volume_ratio=1.3,
           ema_spread_percent=0.3, atr_percent=0.5):
    return {
        "timestamp": index * 300_000,
        "side": "BUY",
        "atr": 0.1,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "ema_spread_percent": ema_spread_percent,
        "atr_percent": atr_percent,
    }


class EntryFilterComparisonTests(unittest.TestCase):
    def test_fixed_filters_select_expected_candidate_counts(self):
        rows = [signal(0), signal(1, rsi=52), signal(2, volume_ratio=1.0),
                signal(3, ema_spread_percent=0.1), signal(4, atr_percent=1.2)]
        result = compare_entry_filters(candles(), rows)
        self.assertEqual(set(result), set(FILTERS))
        self.assertEqual(result["baseline_all_5of5"]["candidate_signal_count"], 5)
        self.assertEqual(result["rsi_at_least_55"]["candidate_signal_count"], 4)
        self.assertEqual(result["rsi_at_least_60"]["candidate_signal_count"], 0)
        self.assertEqual(result["relative_volume_at_least_1_2"]["candidate_signal_count"], 4)
        self.assertEqual(result["ema_spread_at_least_0_25"]["candidate_signal_count"], 4)
        self.assertEqual(result["atr_percent_at_most_1"]["candidate_signal_count"], 4)
        self.assertEqual(result["combined_quality_filter"]["candidate_signal_count"], 1)

    def test_rejects_missing_metrics(self):
        with self.assertRaises(ValueError):
            compare_entry_filters(candles(), [{"timestamp": 0, "side": "BUY", "atr": 1}])

    def test_aggregate_keeps_folds_independent(self):
        fold = compare_entry_filters(candles(), [signal(0)])
        result = aggregate_entry_filter_folds([fold, fold])
        self.assertEqual(result["baseline_all_5of5"]["folds"], 2)
        self.assertEqual(result["baseline_all_5of5"]["candidate_signal_count"], 2)
        self.assertEqual(
            result["baseline_all_5of5"]["equal_allocation_return_percent"],
            result["baseline_all_5of5"]["net_pnl_sum_of_independent_folds"] / 2,
        )


if __name__ == "__main__":
    unittest.main()
