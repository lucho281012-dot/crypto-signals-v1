import copy
import unittest

from signal_engine import analyze_spot


def rising_candles(count=220):
    candles = []
    for index in range(count):
        close = 100.0 + index * 0.15
        candles.append({
            "timestamp": index * 300000,
            "open": close - 0.05,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0 + index,
        })
    return candles


class SignalEngineClosedCandleTests(unittest.TestCase):
    def test_ignores_unclosed_candle_for_signal_decision(self):
        candles_5m = rising_candles()
        candles_15m = rising_candles()

        baseline = analyze_spot(candles_5m, candles_15m)
        self.assertIsNotNone(baseline)
        self.assertEqual(baseline["side"], "BUY")

        changed_5m = copy.deepcopy(candles_5m)
        changed_15m = copy.deepcopy(candles_15m)
        for candles in (changed_5m, changed_15m):
            candles[-1].update({
                "open": 1.0,
                "high": 1_000_000.0,
                "low": 0.01,
                "close": 0.02,
                "volume": 0.0,
            })

        changed = analyze_spot(changed_5m, changed_15m)
        self.assertEqual(changed, baseline)

    def test_rejects_insufficient_history(self):
        self.assertIsNone(analyze_spot(rising_candles(199), rising_candles()))

    def test_buy_signal_has_positive_atr_and_valid_risk_levels(self):
        signal = analyze_spot(rising_candles(), rising_candles())
        self.assertIsNotNone(signal)
        self.assertGreater(signal["atr"], 0)
        self.assertLess(signal["stop"], signal["entry"])
        self.assertGreater(signal["target"], signal["entry"])
        self.assertEqual(signal["conditions_met"], 5)


if __name__ == "__main__":
    unittest.main()
