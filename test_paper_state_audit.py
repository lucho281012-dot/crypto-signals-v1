import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paper_trading as pt
from paper_state_audit import audit_state


class PaperStateAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "paper_state.json"
        self.patch = patch.object(pt, "STATE_FILE", self.state_path)
        self.patch.start()
        self.state = pt.load_state()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_empty_ledger_is_valid(self):
        report = audit_state(self.state)
        self.assertTrue(report["valid"], report["issues"])
        self.assertEqual(report["cash_difference_usdt"], 0.0)

    def test_open_position_reconciles_cash_and_limits(self):
        ok, message = pt.open_position(
            self.state, "SOL/USDT", 75.13, 74.806,
            signal_diagnostic={"decision": "BUY"}
        )
        self.assertTrue(ok, message)
        report = audit_state(self.state)
        self.assertTrue(report["valid"], report["issues"])
        self.assertLessEqual(report["open_investment_usdt"], 30.0 + 1e-8)
        self.assertLessEqual(report["open_risk_usdt"], 2.0 + 1e-8)
        self.assertAlmostEqual(
            report["total_pnl_usdt"],
            report["realized_pnl_usdt"] + report["unrealized_pnl_usdt"],
            places=8,
        )

    def test_audit_is_read_only_and_uses_last_processed_mark(self):
        self.assertTrue(pt.open_position(self.state, "SOL/USDT", 75.13, 74.806)[0])
        self.state["last_processed_close"]["SOL/USDT"] = 76.00
        before = copy.deepcopy(self.state)
        report = audit_state(self.state)
        self.assertTrue(report["valid"], report["issues"])
        self.assertEqual(self.state, before)
        self.assertGreater(report["unrealized_pnl_usdt"], 0)
        self.assertAlmostEqual(
            report["equity_usdt"],
            report["initial_balance_usdt"] + report["total_pnl_usdt"],
            places=8,
        )

    def test_closed_trade_reconciles_cash_and_net_pnl(self):
        ok, message = pt.open_position(self.state, "BTC/USDT", 100, 99)
        self.assertTrue(ok, message)
        ok, message = pt.close_position(self.state, "BTC/USDT", 102, "take_profit")
        self.assertTrue(ok, message)
        report = audit_state(self.state)
        self.assertTrue(report["valid"], report["issues"])
        self.assertEqual(report["closed_trades"], 1)
        self.assertEqual(report["open_positions"], 0)

    def test_detects_corrupted_cash_balance(self):
        self.state["cash_usdt"] -= 0.50
        report = audit_state(self.state)
        self.assertFalse(report["valid"])
        self.assertIn(
            "cash balance does not reconcile with ledger transactions",
            report["issues"]
        )

    def test_detects_corrupted_trade_pnl(self):
        self.assertTrue(pt.open_position(self.state, "ETH/USDT", 100, 99)[0])
        self.assertTrue(pt.close_position(self.state, "ETH/USDT", 101)[0])
        self.state["history"][0]["net_pnl"] += 0.25
        report = audit_state(self.state)
        self.assertFalse(report["valid"])
        self.assertIn("closed trade 0: net PnL does not reconcile", report["issues"])

    def test_detects_risk_and_investment_limit_breaches(self):
        self.assertTrue(pt.open_position(self.state, "BTC/USDT", 100, 99)[0])
        position = self.state["positions"]["BTC/USDT"]
        position["quantity"] *= 2
        position["risk_budget"] = 2.1
        report = audit_state(self.state)
        self.assertFalse(report["valid"])
        self.assertTrue(any("30% portfolio limit" in x for x in report["issues"]))
        self.assertTrue(any("2% portfolio limit" in x for x in report["issues"]))


if __name__ == "__main__":
    unittest.main()
