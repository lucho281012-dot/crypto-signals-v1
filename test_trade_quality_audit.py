import unittest

from trade_quality_audit import build_quality_report


class TradeQualityAuditTests(unittest.TestCase):
    def test_groups_by_symbol_and_exit_reason_and_reconciles_pnl(self):
        state = {
            "positions": {"SOL/USDT": {}},
            "history": [
                {
                    "symbol": "BTC/USDT", "reason": "stop_loss",
                    "quantity": 1.0, "entry_price": 10.0, "exit_price": 9.0,
                    "entry_fee": 0.01, "exit_fee": 0.009,
                    "net_pnl": -1.019, "stop_price": 9.0,
                    "opened_at": "2026-01-01T00:00:00+00:00",
                    "closed_at": "2026-01-01T01:00:00+00:00",
                },
                {
                    "symbol": "BTC/USDT", "reason": "take_profit",
                    "quantity": 1.0, "entry_price": 10.0, "exit_price": 12.0,
                    "entry_fee": 0.01, "exit_fee": 0.012,
                    "net_pnl": 1.978, "stop_price": 9.0,
                    "signal_diagnostic": {"rsi": 60},
                },
            ],
        }
        report = build_quality_report(state)
        self.assertEqual(report["closed_trade_summary"]["trades"], 2)
        self.assertAlmostEqual(report["closed_trade_summary"]["net_pnl_usdt"], 0.959)
        self.assertEqual(report["by_symbol"]["BTC/USDT"]["trades"], 2)
        self.assertEqual(report["by_exit_reason"]["stop_loss"]["trades"], 1)
        self.assertEqual(report["closed_trades_with_entry_context"], 1)
        self.assertEqual(report["closed_trades_missing_entry_context"], 1)
        self.assertEqual(report["open_positions_not_scored"], 1)
        self.assertEqual(report["pnl_mismatches"], [])
        self.assertAlmostEqual(report["trade_details"][0]["holding_minutes"], 60.0)

    def test_r_multiple_prefers_recorded_entry_risk_budget(self):
        state = {"history": [{
            "symbol": "BTC/USDT", "reason": "take_profit",
            "quantity": 1.0, "entry_price": 10.0, "exit_price": 11.0,
            "entry_fee": 0.0, "exit_fee": 0.0, "net_pnl": 1.0,
            "stop_price": 9.0, "risk_budget": 0.25,
        }]}
        report = build_quality_report(state)
        self.assertAlmostEqual(report["trade_details"][0]["r_multiple"], 4.0)
        self.assertAlmostEqual(report["closed_trade_summary"]["average_r_multiple"], 4.0)

    def test_reports_inconsistent_net_pnl(self):
        state = {"history": [{
            "symbol": "ETH/USDT", "quantity": 1, "entry_price": 10,
            "exit_price": 11, "entry_fee": 0.1, "exit_fee": 0.1,
            "net_pnl": 2.0,
        }]}
        report = build_quality_report(state)
        self.assertEqual(len(report["pnl_mismatches"]), 1)


if __name__ == "__main__":
    unittest.main()
