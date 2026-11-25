import unittest
from unittest.mock import patch

from paper_trading import (
    open_position,
    open_positions_batch,
    risk_per_unit,
    calculate_open_risk,
)


class PaperTradingRiskTests(unittest.TestCase):
    def state(self, cash=100.0, positions=None):
        return {
            "initial_balance": 100.0,
            "cash_usdt": cash,
            "positions": positions or {},
            "history": [],
        }

    def test_risk_includes_exit_slippage_and_both_fees(self):
        expected_exit = 9.0 * (1 - 5 / 10000)
        expected = 10.0 - expected_exit + 10.0 * 0.001 + expected_exit * 0.001
        self.assertAlmostEqual(risk_per_unit(10.0, 9.0), expected)

    def test_cash_cap_records_actual_risk_not_full_target(self):
        state = self.state(cash=5.0)
        with patch("paper_trading.save_state"):
            success, message = open_position(state, "BTC/USDT", 10.0, 9.0)

        self.assertTrue(success, message)
        position = state["positions"]["BTC/USDT"]
        self.assertLess(position["risk_budget"], position["risk_budget_target"])
        self.assertAlmostEqual(
            position["risk_budget"],
            position["quantity"] * risk_per_unit(10.0, 9.0),
        )
        self.assertAlmostEqual(position["risk_budget_target"], 1.0)

    def test_single_position_uses_aggregate_one_percent_risk_cap(self):
        state = self.state()
        with patch("paper_trading.save_state"):
            result = open_positions_batch(state, [{
                "symbol": "BTC/USDT", "entry_price": 10.0, "stop_price": 9.0
            }])
        self.assertTrue(result["BTC/USDT"][0])
        self.assertLessEqual(calculate_open_risk(state), 1.0 + 1e-9)

    def test_simultaneous_signals_share_one_risk_budget_proportionally(self):
        state = self.state()
        candidates = [
            {"symbol": "BTC/USDT", "entry_price": 10.0, "stop_price": 9.8},
            {"symbol": "ETH/USDT", "entry_price": 10.0, "stop_price": 9.8},
        ]
        with patch("paper_trading.save_state"):
            result = open_positions_batch(state, candidates)

        self.assertTrue(result["BTC/USDT"][0])
        self.assertTrue(result["ETH/USDT"][0])
        risk = calculate_open_risk(state)
        self.assertLessEqual(risk, 1.0 + 1e-9)
        self.assertAlmostEqual(
            state["positions"]["BTC/USDT"]["risk_budget"],
            state["positions"]["ETH/USDT"]["risk_budget"],
        )

    def test_existing_position_risk_is_recomputed_not_trusted_from_stored_budget(self):
        existing = {
            "BTC/USDT": {
                "entry_price": 10.0, "stop_price": 9.0,
                "quantity": 1.0, "entry_fee": 0.01,
                "risk_budget": 0.0,
            }
        }
        state = self.state(positions=existing)
        with patch("paper_trading.save_state"):
            result = open_positions_batch(state, [{
                "symbol": "ETH/USDT", "entry_price": 10.0, "stop_price": 9.8
            }])
        self.assertFalse(result["ETH/USDT"][0])
        self.assertNotIn("ETH/USDT", state["positions"])

    def test_position_below_five_usdt_is_rejected_without_mutation(self):
        state = self.state(cash=1.0)
        before_cash = state["cash_usdt"]
        with patch("paper_trading.save_state") as save:
            result = open_positions_batch(state, [{
                "symbol": "BTC/USDT", "entry_price": 10.0, "stop_price": 9.0
            }])
        self.assertFalse(result["BTC/USDT"][0])
        self.assertNotIn("BTC/USDT", state["positions"])
        self.assertEqual(state["cash_usdt"], before_cash)
        save.assert_not_called()

    def test_unverifiable_existing_position_blocks_all_new_entries(self):
        state = self.state(positions={
            "BTC/USDT": {"quantity": 1.0, "entry_price": 10.0}
        })
        with patch("paper_trading.save_state") as save:
            result = open_positions_batch(state, [{
                "symbol": "ETH/USDT", "entry_price": 10.0, "stop_price": 9.8
            }])
        self.assertFalse(result["ETH/USDT"][0])
        self.assertNotIn("ETH/USDT", state["positions"])
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
