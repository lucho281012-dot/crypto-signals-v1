import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paper_trading as pt


class EntryContextCapitalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "paper_state.json"
        self.patch = patch.object(pt, "STATE_FILE", self.state_path)
        self.patch.start()
        self.state = pt.load_state()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_fresh_ledger_is_separate_and_starts_at_100(self):
        self.assertEqual(self.state["cash_usdt"], 100.0)
        self.assertEqual(self.state["history"], [])
        self.assertEqual(self.state["positions"], {})

    def test_investment_never_exceeds_30_percent(self):
        ok, message = pt.open_position(self.state, "BTC/USDT", 100, 99)
        self.assertTrue(ok, message)
        invested = sum(
            p["quantity"] * p["entry_price"]
            for p in self.state["positions"].values()
        )
        self.assertLessEqual(invested, 30.0 + 1e-9)

    def test_aggregate_open_risk_never_exceeds_2_percent(self):
        for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
            pt.open_position(self.state, symbol, 100, 90)
        risk = sum(p["risk_budget"] for p in self.state["positions"].values())
        self.assertLessEqual(risk, 2.0 + 1e-9)

    def test_remaining_aggregate_risk_blocks_third_position(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 90)[0])
        self.assertTrue(pt.open_position(self.state, "ETH/USDT", 100, 90)[0])
        self.assertAlmostEqual(
            sum(p["risk_budget"] for p in self.state["positions"].values()),
            2.0, places=8
        )
        ok, message = pt.open_position(self.state, "SOL/USDT", 100, 90)
        self.assertFalse(ok)
        self.assertEqual(message, "Límite de riesgo agregado alcanzado")

    def test_signal_context_survives_close(self):
        diagnostic = {"schema_version": 1, "decision": "BUY"}
        ok, message = pt.open_position(
            self.state, "BTC/USDT", 100, 99,
            signal_diagnostic=diagnostic
        )
        self.assertTrue(ok, message)
        self.assertTrue(pt.close_position(self.state, "BTC/USDT", 101)[0])
        self.assertEqual(
            self.state["history"][-1]["signal_diagnostic"], diagnostic
        )

    def test_equity_and_portfolio_limits_are_reported(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 99)[0])
        self.state["last_processed_close"]["BTC/USDT"] = 105
        status = pt.get_status(self.state)
        self.assertEqual(status["investment_limit_usdt"], 30.0)
        self.assertEqual(status["open_risk_limit_usdt"], 2.0)
        self.assertGreater(status["equity_usdt"], 100)
        self.assertAlmostEqual(
            status["total_pnl"], status["equity_usdt"] - 100, places=4
        )

    def test_duplicate_and_invalid_positions_are_rejected(self):
        self.assertFalse(pt.open_position(self.state, "BTC/USDT", 0, -1)[0])
        self.assertFalse(pt.open_position(self.state, "BTC/USDT", 100, 100)[0])
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 99)[0])
        self.assertFalse(pt.open_position(self.state, "BTC/USDT", 101, 99)[0])


if __name__ == "__main__":
    unittest.main()
