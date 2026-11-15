import unittest

from historical_segment_backtest import generate_segment_signals


def rising(count, interval, first):
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


class HistoricalSegmentBacktestTests(unittest.TestCase):
    def test_uses_only_fully_closed_aligned_15m_and_leaves_last_5m_untraded(self):
        five = rising(620, 300_000, 0)
        # Last 5m close at 3,100 minutes; selected 15m bar opens at 3,090.
        last_15_open = ((five[-1]["timestamp"] + 300_000) // 900_000) * 900_000 - 900_000
        fifteen = rising(207, 900_000, last_15_open - 206 * 900_000)
        signals = generate_segment_signals(five, fifteen)
        self.assertTrue(signals)
        self.assertLess(signals[-1]["timestamp"], five[-1]["timestamp"])
        self.assertTrue(all(s["timestamp"] in {c["timestamp"] for c in five[:-1]} for s in signals))

    def test_requires_indicator_warmup_in_both_timeframes(self):
        five = rising(599, 300_000, 0)
        last_15_open = ((five[-1]["timestamp"] + 300_000) // 900_000) * 900_000 - 900_000
        fifteen = rising(199, 900_000, last_15_open - 198 * 900_000)
        self.assertEqual(generate_segment_signals(five, fifteen), [])


if __name__ == "__main__":
    unittest.main()
