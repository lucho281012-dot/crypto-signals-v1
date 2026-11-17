import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paper_trading as pt


class PaperTradingCapitalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "paper_state.json"
        self.patch = patch.object(pt, "STATE_FILE", self.state_path)
        self.patch.start()
        self.state = pt.load_state()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_position_investment_never_exceeds_30_percent(self):
        ok, message = pt.open_position(self.state, "BTC/USDT", 100, 90)
        self.assertTrue(ok, message)
        invested = sum(p["quantity"] * p["entry_price"] for p in self.state["positions"].values())
        self.assertLessEqual(invested, 30.0 + 1e-9)

    def test_aggregate_open_risk_never_exceeds_2_percent(self):
        for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
            pt.open_position(self.state, symbol, 100, 90)
        risk = sum(p["risk_budget"] for p in self.state["positions"].values())
        self.assertLessEqual(risk, 2.0 + 1e-9)

    def test_second_position_uses_only_remaining_aggregate_risk(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 90)[0])
        self.assertTrue(pt.open_position(self.state, "ETH/USDT", 100, 90)[0])
        self.assertAlmostEqual(
            sum(p["risk_budget"] for p in self.state["positions"].values()), 2.0, places=8
        )
        ok, message = pt.open_position(self.state, "SOL/USDT", 100, 90)
        self.assertFalse(ok)
        self.assertEqual(message, "Límite de riesgo agregado alcanzado")

    def test_equity_includes_mark_to_market_and_fees(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 90)[0])
        status = pt.get_status(self.state, {"BTC/USDT": 110})
        self.assertGreater(status["equity_usdt"], 100)
        self.assertAlmostEqual(
            status["total_pnl"], status["equity_usdt"] - 100, places=4
        )
        self.assertGreater(status["unrealized_pnl"], 0)

    def test_equity_uses_last_processed_close_when_no_live_mark_passed(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 90)[0])
        self.state["last_processed_close"]["BTC/USDT"] = 105
        status = pt.get_status(self.state)
        self.assertGreater(status["equity_usdt"], 100)

    def test_duplicate_symbol_is_rejected(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 90)[0])
        ok, _ = pt.open_position(self.state, "BTC/USDT", 101, 90)
        self.assertFalse(ok)

    def test_close_position_records_both_fees(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 90)[0])
        pos = self.state["positions"]["BTC/USDT"]
        expected = pos["quantity"] * 110 * (1 - pt.FEE_RATE) - pos["quantity"] * 100 - pos["entry_fee"]
        self.assertTrue(pt.close_position(self.state, "BTC/USDT", 110)[0])
        self.assertAlmostEqual(self.state["history"][-1]["net_pnl"], expected)

    def test_rejects_invalid_prices(self):
        self.assertFalse(pt.open_position(self.state, "BTC/USDT", 0, -1)[0])
        self.assertFalse(pt.open_position(self.state, "BTC/USDT", 100, 100)[0])


if __name__ == "__main__":
    unittest.main()
