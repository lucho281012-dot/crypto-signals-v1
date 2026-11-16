import unittest
from unittest.mock import patch

from paper_trading import open_position


class PaperTradingRiskTests(unittest.TestCase):
    def test_cash_cap_records_actual_risk_not_full_target(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 5.0,
            "positions": {},
            "history": [],
        }
        with patch("paper_trading.save_state"):
            success, message = open_position(state, "BTC/USDT", 10.0, 9.0)

        self.assertTrue(success, message)
        position = state["positions"]["BTC/USDT"]
        self.assertLess(position["risk_budget"], position["risk_budget_target"])
        self.assertAlmostEqual(
            position["risk_budget"],
            position["quantity"] * (10.0 - 9.0 + 10.0 * 0.001 + 9.0 * 0.001),
        )
        self.assertAlmostEqual(position["risk_budget_target"], 1.0)

    def test_risk_target_and_actual_risk_match_when_not_capped(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 100.0,
            "positions": {},
            "history": [],
        }
        with patch("paper_trading.save_state"):
            success, message = open_position(state, "BTC/USDT", 10.0, 9.0)

        self.assertTrue(success, message)
        position = state["positions"]["BTC/USDT"]
        self.assertAlmostEqual(position["risk_budget"], 1.0)
        self.assertAlmostEqual(position["risk_budget_target"], 1.0)


if __name__ == "__main__":
    unittest.main()
