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


    def test_calculates_stop_risk_r_multiple_and_symbol_breakdown(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 99.0,
            "positions": {},
            "history": [{
                "symbol": "BTC/USDT",
                "quantity": 1.0,
                "entry_price": 10.0,
                "stop_price": 9.0,
                "exit_price": 11.0,
                "entry_fee": 0.01,
                "exit_fee": 0.011,
                "net_pnl": 0.979,
                "risk_budget": 1.0,
            }],
        }
        report = build_audit(state)
        risk = report["risk_analysis_per_trade"][0]
        btc = report["performance_by_symbol"]["BTC/USDT"]

        self.assertAlmostEqual(risk["estimated_loss_at_stop_usdt"], 1.019)
        self.assertAlmostEqual(risk["risk_percent_of_initial_balance"], 1.019)
        self.assertAlmostEqual(risk["realized_r_multiple"], 0.979 / 1.019, places=5)
        self.assertEqual(btc["trades"], 1)
        self.assertEqual(btc["wins"], 1)
        self.assertAlmostEqual(btc["net_pnl_usdt"], 0.979)

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


    def test_reports_aggregate_open_risk_exposure_and_dust(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 89.99,
            "positions": {
                "BTC/USDT": {
                    "quantity": 1.0,
                    "entry_price": 10.0,
                    "stop_price": 9.0,
                    "entry_fee": 0.01,
                    "opened_at": "2026-01-01T00:00:00+00:00",
                }
            },
            "history": [],
        }
        report = build_audit(state)
        limits = report["portfolio_limits"]
        sizes = report["position_size_audit"]

        self.assertGreater(limits["open_risk_usdt"], 1.0)
        self.assertFalse(limits["open_risk_within_limit"])
        self.assertAlmostEqual(limits["open_exposure_usdt"], 10.0)
        self.assertTrue(limits["open_exposure_within_limit"])
        self.assertEqual(sizes["below_minimum_notional_count"], 0)
        self.assertFalse(limits["historical_reconstruction_complete"])

    def test_reports_missing_execution_metadata_for_legacy_trades(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 100.0,
            "positions": {},
            "history": [{
                "symbol": "BTC/USDT", "quantity": 1.0,
                "entry_price": 10.0, "stop_price": 9.0,
                "exit_price": 10.0, "entry_fee": 0.01,
                "exit_fee": 0.01, "net_pnl": -0.02,
                "opened_at": "2026-01-01T00:00:00+00:00",
                "closed_at": "2026-01-01T00:05:00+00:00",
            }],
        }
        report = build_audit(state)
        trace = report["execution_traceability"]
        self.assertEqual(trace["records_with_complete_entry_metadata"], 0)
        self.assertEqual(trace["coverage_percent"], 0.0)
        self.assertTrue(report["portfolio_limits"]["historical_reconstruction_complete"])
        self.assertEqual(report["position_size_audit"]["below_minimum_notional_count"], 0)


if __name__ == "__main__":
    unittest.main()
