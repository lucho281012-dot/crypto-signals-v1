"""Tests for the read-only connection to the active Paper state model."""
import copy
import unittest

from paper_report_dry_run import build_read_only_report


class ReadOnlyPaperReportTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "initial_balance": 1000,
            "cash_usdt": 899.9,
            "positions": {
                "BTC/USDT": {
                    "quantity": 1,
                    "entry_price": 100,
                    "entry_fee": 0.1,
                    "stop_price": 90,
                    "risk_budget": 10,
                    "opened_at": "2026-11-15T10:00:00Z",
                }
            },
            "history": [],
            "last_processed_candle": {"BTC/USDT": "123"},
        }
        self.original_state = copy.deepcopy(self.state)

    def test_builds_report_using_public_price_without_mutating_state(self):
        report = build_read_only_report(
            self.state, {"BTC/USDT": {"price": 110}}
        )
        self.assertEqual(report["equity_usdt"], "1009.9")
        self.assertEqual(report["unrealized_pnl_usdt"], "9.9")
        self.assertEqual(report["open_position_count"], 1)
        self.assertEqual(self.state, self.original_state)

    def test_missing_market_mark_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "missing public market price"):
            build_read_only_report(self.state, {})
        self.assertEqual(self.state, self.original_state)

    def test_empty_portfolio_needs_no_market_data(self):
        state = {
            "initial_balance": 100,
            "cash_usdt": 100,
            "positions": {},
            "history": [],
        }
        report = build_read_only_report(state, {})
        self.assertEqual(report["equity_usdt"], "100")
        self.assertEqual(report["open_position_count"], 0)


if __name__ == "__main__":
    unittest.main()
