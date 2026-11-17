import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paper_trading as pt


class PaperTradingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "paper_state.json"
        self.state_patch = patch.object(pt, "STATE_FILE", self.state_path)
        self.state_patch.start()
        self.state = pt.load_state()

    def tearDown(self):
        self.state_patch.stop()
        self.tmp.cleanup()

    def test_open_position_accounts_for_entry_fee_and_risk_cap(self):
        ok, message = pt.open_position(self.state, "BTC/USDT", 100.0, 99.0)
        self.assertTrue(ok, message)
        position = self.state["positions"]["BTC/USDT"]
        self.assertGreater(position["quantity"], 0)
        self.assertAlmostEqual(position["entry_fee"], position["quantity"] * 100 * pt.FEE_RATE)
        self.assertLessEqual(position["risk_budget"], position["risk_budget_target"])
        self.assertLess(self.state["cash_usdt"], 100.0)

    def test_prevents_duplicate_position_for_same_symbol(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 99)[0])
        ok, message = pt.open_position(self.state, "BTC/USDT", 101, 100)
        self.assertFalse(ok)
        self.assertEqual(message, "Ya existe una posición abierta")

    def test_close_position_records_net_pnl_after_both_fees(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 99)[0])
        position = self.state["positions"]["BTC/USDT"]
        quantity = position["quantity"]
        entry_fee = position["entry_fee"]
        ok, _ = pt.close_position(self.state, "BTC/USDT", 110, "take_profit")
        self.assertTrue(ok)
        trade = self.state["history"][-1]
        expected = quantity * 110 * (1 - pt.FEE_RATE) - quantity * 100 - entry_fee
        self.assertAlmostEqual(trade["net_pnl"], expected)
        self.assertNotIn("BTC/USDT", self.state["positions"])

    def test_symbols_can_have_independent_positions(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 99)[0])
        self.assertTrue(pt.open_position(self.state, "ETH/USDT", 100, 99)[0])
        self.assertEqual(set(self.state["positions"]), {"BTC/USDT", "ETH/USDT"})

    def test_rejects_invalid_stop(self):
        ok, _ = pt.open_position(self.state, "BTC/USDT", 100, 100)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
