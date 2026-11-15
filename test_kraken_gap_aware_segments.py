import unittest

from kraken_gap_aware_segments import build_aligned_contiguous_segments

FIVE = 300_000
FIFTEEN = 900_000


def candles(count, interval, start):
    rows = []
    for i in range(count):
        price = 100.0 + i * 0.01
        rows.append({
            "timestamp": start + i * interval,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price + 0.2,
            "volume": 10.0,
            "trades": 3,
        })
    return rows


class GapAwareSegmentTests(unittest.TestCase):
    def test_builds_aligned_segments_and_only_uses_closed_15m_bars(self):
        five = candles(900, FIVE, 900_000)
        fifteen = candles(301, FIFTEEN, 0)
        result = build_aligned_contiguous_segments(five, fifteen)
        self.assertEqual(result["metadata"]["usable_segments"], 1)
        segment = result["segments"][0]
        self.assertEqual(len(segment["candles_5m"]), 900)
        self.assertEqual(len(segment["candles_15m"]), 300)
        last_5m_close = segment["candles_5m"][-1]["timestamp"] + FIVE
        expected_15m = (last_5m_close // FIFTEEN) * FIFTEEN - FIFTEEN
        self.assertEqual(segment["candles_15m"][-1]["timestamp"], expected_15m)
        self.assertFalse(result["metadata"]["gaps_filled"])
        self.assertEqual(result["metadata"]["candles_fabricated"], 0)

    def test_splits_at_missing_5m_candle_without_bridging(self):
        five = candles(1200, FIVE, 900_000)
        del five[600]
        fifteen = candles(401, FIFTEEN, 0)
        result = build_aligned_contiguous_segments(five, fifteen)
        self.assertEqual(result["metadata"]["usable_segments"], 2)
        first, second = result["segments"]
        self.assertEqual(first["candles_5m"][-1]["timestamp"] + FIVE,
                         second["candles_5m"][0]["timestamp"])
        self.assertEqual(first["candles_5m"][-1]["timestamp"], five[599]["timestamp"])
        self.assertEqual(second["candles_5m"][0]["timestamp"], five[600]["timestamp"])
        for segment in result["segments"]:
            for a, b in zip(segment["candles_5m"], segment["candles_5m"][1:]):
                self.assertEqual(b["timestamp"] - a["timestamp"], FIVE)

    def test_splits_when_required_15m_candle_is_missing(self):
        five = candles(1200, FIVE, 900_000)
        fifteen = candles(401, FIFTEEN, 0)
        del fifteen[200]
        result = build_aligned_contiguous_segments(five, fifteen)
        self.assertGreaterEqual(result["metadata"]["fifteen_minute_discontinuities"], 1)
        self.assertGreaterEqual(result["metadata"]["usable_segments"], 1)
        for segment in result["segments"]:
            for a, b in zip(segment["candles_15m"], segment["candles_15m"][1:]):
                self.assertEqual(b["timestamp"] - a["timestamp"], FIFTEEN)

    def test_drops_segments_below_minimum_history(self):
        five = candles(300, FIVE, 900_000)
        fifteen = candles(101, FIFTEEN, 0)
        result = build_aligned_contiguous_segments(
            five, fifteen, min_5m_candles=200, min_15m_candles=200
        )
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["metadata"]["usable_segments"], 0)

    def test_rejects_unsorted_or_duplicate_timestamps(self):
        five = candles(300, FIVE, 900_000)
        five[100]["timestamp"] = five[99]["timestamp"]
        fifteen = candles(101, FIFTEEN, 0)
        with self.assertRaisesRegex(ValueError, "duplicados o desordenados"):
            build_aligned_contiguous_segments(five, fifteen)

    def test_rejects_unaligned_timestamps(self):
        five = candles(300, FIVE, 900_000)
        five[10]["timestamp"] += 1
        fifteen = candles(101, FIFTEEN, 0)
        with self.assertRaisesRegex(ValueError, "fuera de alineación"):
            build_aligned_contiguous_segments(five, fifteen)


if __name__ == "__main__":
    unittest.main()
