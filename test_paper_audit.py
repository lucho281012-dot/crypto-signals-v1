import unittest

from paper_audit import build_audit


class PaperAuditTests(unittest.TestCase):
    def test_reconciles_closed_trades_and_calculates_metrics(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 100.0 + 1.8 - 1.2,
            "positions": {},
            "history": [
                {
                    "symbol": "BTC/USDT", "quantity": 1.0,
                    "entry_price": 10.0, "exit_price": 12.0,
                    "entry_fee": 0.1, "exit_fee": 0.1,
                    "net_pnl": 1.8, "closed_at": "2026-01-01T00:00:00Z"
                },
                {
                    "symbol": "ETH/USDT", "quantity": 1.0,
                    "entry_price": 10.0, "exit_price": 9.0,
                    "entry_fee": 0.1, "exit_fee": 0.1,
                    "net_pnl": -1.2, "closed_at": "2026-01-02T00:00:00Z"
                },
            ],
        }
        report = build_audit(state)
        self.assertTrue(report["cash_reconciles"])
        self.assertEqual(report["closed_trades"], 2)
        self.assertEqual(report["wins"], 1)
        self.assertEqual(report["losses"], 1)
        self.assertAlmostEqual(report["net_realized_pnl_usdt"], 0.6)
        self.assertAlmostEqual(report["profit_factor"], 1.5)
        self.assertEqual(report["pnl_mismatches"], [])

    def test_includes_open_position_cost_and_entry_fee_in_cash_reconciliation(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 89.89,
            "positions": {
                "BTC/USDT": {
                    "quantity": 1.0, "entry_price": 10.0, "entry_fee": 0.11
                }
            },
            "history": [],
        }
        report = build_audit(state)
        self.assertTrue(report["cash_reconciles"])
        self.assertEqual(report["open_positions"], 1)
        self.assertEqual(report["closed_trades"], 0)
        self.assertIsNone(report["profit_factor"])

    def test_detects_cash_and_trade_pnl_mismatch(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 99.0,
            "positions": {},
            "history": [{
                "symbol": "BTC/USDT", "quantity": 1.0,
                "entry_price": 10.0, "exit_price": 11.0,
                "entry_fee": 0.1, "exit_fee": 0.1,
                "net_pnl": 0.9,
            }],
        }
        report = build_audit(state)
        self.assertFalse(report["cash_reconciles"])
        self.assertEqual(len(report["pnl_mismatches"]), 1)


if __name__ == "__main__":
    unittest.main()
