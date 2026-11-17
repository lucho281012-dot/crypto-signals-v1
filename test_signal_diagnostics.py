import unittest

from signal_engine import analyze_spot, evaluate_spot


def make_candles(count=220, rising=True):
    candles = []
    for index in range(count):
        base = 100 + index * (0.2 if rising else -0.2)
        candles.append({
            "timestamp": 1_800_000_000_000 + index * 300_000,
            "open": base,
            "high": base + 0.3,
            "low": base - 0.3,
            "close": base + 0.1,
            "volume": 100.0,
        })
    # The penultimate candle is the latest closed candle selected by the engine.
    candles[-2]["volume"] = 250.0
    return candles


class SignalDiagnosticsTests(unittest.TestCase):
    def test_diagnostic_records_closed_candle_filters_and_buy(self):
        candles_5m = make_candles()
        candles_15m = make_candles()
        result = evaluate_spot(candles_5m, candles_15m)

        self.assertIsNotNone(result)
        diagnostic = result["diagnostic"]
        self.assertEqual(diagnostic["candle_timestamp"], candles_5m[-2]["timestamp"])
        self.assertEqual(diagnostic["side"], "BUY")
        self.assertEqual(diagnostic["conditions_met"], 5)
        self.assertTrue(diagnostic["trend_15m_bullish"])
        self.assertTrue(all(diagnostic["conditions"].values()))
        self.assertIn("rsi14", diagnostic["indicators"])
        self.assertIn("volume_ratio", diagnostic["indicators"])
        self.assertEqual(analyze_spot(candles_5m, candles_15m), result["signal"])

    def test_diagnostic_records_no_signal_without_changing_signal_interface(self):
        candles_5m = make_candles(rising=False)
        candles_15m = make_candles(rising=False)
        result = evaluate_spot(candles_5m, candles_15m)

        self.assertIsNotNone(result)
        self.assertEqual(result["diagnostic"]["side"], "NO_SIGNAL")
        self.assertIsNone(result["signal"])
        self.assertIsNone(analyze_spot(candles_5m, candles_15m))


if __name__ == "__main__":
    unittest.main()
