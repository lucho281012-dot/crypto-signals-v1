import unittest

from signal_engine import analyze_spot


def make_candles(count, interval_ms, volume_spike=True):
    candles = []
    for index in range(count):
        close = 100.0 + 0.002 * (index ** 2)
        volume = 250.0 if volume_spike and index == count - 2 else 100.0
        candles.append({
            "timestamp": index * interval_ms,
            "open": close - 0.1,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": volume,
        })
    return candles


class SignalDiagnosticTests(unittest.TestCase):
    def test_buy_keeps_existing_decision_and_records_closed_candle_context(self):
        candles_5m = make_candles(220, 300_000)
        candles_15m = make_candles(220, 900_000)

        result = analyze_spot(candles_5m, candles_15m)

        self.assertIsNotNone(result)
        self.assertEqual(result["side"], "BUY")
        self.assertEqual(result["conditions_met"], 5)

        diagnostic = result["signal_diagnostic"]
        self.assertEqual(diagnostic["schema_version"], 1)
        self.assertEqual(diagnostic["strategy"], "spot_v1")
        self.assertEqual(diagnostic["decision"], "BUY")
        self.assertEqual(
            diagnostic["signal_candle_timestamp_5m"],
            candles_5m[-2]["timestamp"],
        )
        self.assertEqual(
            diagnostic["trend_candle_timestamp_15m"],
            candles_15m[-2]["timestamp"],
        )
        self.assertEqual(diagnostic["required_conditions"], 4)
        self.assertTrue(all(diagnostic["conditions"].values()))
        self.assertGreater(diagnostic["indicators_5m"]["atr14"], 0)
        self.assertTrue(diagnostic["bullish_trend_15m"])

    def test_open_candle_does_not_change_signal_diagnostic(self):
        candles_5m = make_candles(220, 300_000)
        candles_15m = make_candles(220, 900_000)
        first = analyze_spot(candles_5m, candles_15m)

        # Alteramos somente a vela [-1], que ainda está em formação.
        candles_5m[-1]["close"] = 1.0
        candles_5m[-1]["volume"] = 1_000_000.0
        second = analyze_spot(candles_5m, candles_15m)

        self.assertEqual(first["side"], second["side"])
        self.assertEqual(
            first["signal_diagnostic"],
            second["signal_diagnostic"],
        )

    def test_insufficient_history_still_returns_no_signal(self):
        result = analyze_spot(
            make_candles(199, 300_000),
            make_candles(220, 900_000),
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
