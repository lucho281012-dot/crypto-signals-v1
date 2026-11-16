import unittest

from strategy_research import calculate_quantity, resolve_exit


class StrategyResearchTests(unittest.TestCase):
    def test_stop_has_priority_when_stop_and_target_hit_same_candle(self):
        position = {"stop": 95.0, "target": 110.0}
        candle = {"open": 100.0, "low": 94.0, "high": 111.0}
        self.assertEqual(resolve_exit(position, candle), (95.0, "stop_loss"))

    def test_gap_below_stop_uses_open_price(self):
        position = {"stop": 95.0, "target": 110.0}
        candle = {"open": 90.0, "low": 89.0, "high": 93.0}
        self.assertEqual(resolve_exit(position, candle), (90.0, "stop_loss"))

    def test_quantity_respects_risk_and_capital_limit(self):
        quantity = calculate_quantity(100.0, 100.0, 99.0)
        estimated_risk = quantity * (100.0 - 99.0 + 0.1 + 0.099)
        invested = quantity * 100.0 * 1.001
        self.assertLessEqual(estimated_risk, 1.0 + 1e-9)
        self.assertLessEqual(invested, 95.0 + 1e-9)

    def test_invalid_stop_returns_zero_quantity(self):
        self.assertEqual(calculate_quantity(100.0, 100.0, 100.0), 0.0)


if __name__ == "__main__":
    unittest.main()
