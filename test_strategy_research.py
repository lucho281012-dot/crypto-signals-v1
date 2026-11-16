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

    def test_latest_closed_trend_ignores_unclosed_15m_candle(self):
        import pandas as pd
        from strategy_research import latest_closed_trend

        fifteen = pd.DataFrame([
            {"timestamp": 0, "ema20": 10.0, "ema200": 9.0},
            {"timestamp": 900_000, "ema20": 8.0, "ema200": 9.0},
        ])
        # A 5m candle starting at 600,000 closes at 900,000:
        # the 15m candle starting at 900,000 is not yet closed.
        trend = latest_closed_trend(600_000, fifteen)
        self.assertEqual(int(trend["timestamp"]), 0)

    def test_latest_closed_trend_uses_newly_closed_15m_candle(self):
        import pandas as pd
        from strategy_research import latest_closed_trend

        fifteen = pd.DataFrame([
            {"timestamp": 0, "ema20": 10.0, "ema200": 9.0},
            {"timestamp": 900_000, "ema20": 8.0, "ema200": 9.0},
        ])
        # A 5m candle starting at 1,500,000 closes at 1,800,000,
        # so the 15m candle starting at 900,000 is fully closed.
        trend = latest_closed_trend(1_500_000, fifteen)
        self.assertEqual(int(trend["timestamp"]), 900_000)

    def test_latest_closed_trend_returns_none_without_completed_candle(self):
        import pandas as pd
        from strategy_research import latest_closed_trend

        fifteen = pd.DataFrame([
            {"timestamp": 900_000, "ema20": 10.0, "ema200": 9.0},
        ])
        self.assertIsNone(latest_closed_trend(0, fifteen))


if __name__ == "__main__":
    unittest.main()
