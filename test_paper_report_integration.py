"""End-to-end validation from legacy Paper state to Dashboard history."""
import unittest

from paper_legacy_report_adapter import build_legacy_paper_report
from paper_report_dashboard import build_report_dashboard_model
from paper_report_export import export_report_history_csv
from paper_report_history import (
    append_report_snapshot,
    build_report_snapshot,
    deserialize_report_history,
    serialize_report_history,
)


class LegacyPaperDashboardIntegrationTests(unittest.TestCase):
    def test_legacy_state_to_serialized_dashboard_history(self):
        # Closed trade: 1 BTC bought at 100 with 0.10 fee, sold at 110
        # with 0.11 fee. Net realized P&L is 9.79 USDT.
        state_after_close = {
            "initial_balance": 1000,
            "cash_usdt": 1009.79,
            "positions": {},
            "history": [{
                "symbol": "BTC/USDT",
                "quantity": 1,
                "entry_price": 100,
                "entry_fee": 0.10,
                "exit_fee": 0.11,
                "net_pnl": 9.79,
            }],
        }
        first_report = build_legacy_paper_report(state_after_close, {})
        first = build_report_snapshot(
            first_report, "2026-11-15T10:00:00Z", "integration-001"
        )

        # A second, still-open BTC position: 2 BTC at 50, entry fee 0.10,
        # marked at 55. Equity must reconcile to realized + unrealized P&L.
        state_with_open_position = {
            "initial_balance": 1000,
            "cash_usdt": 909.69,
            "positions": {
                "BTC/USDT": {
                    "quantity": 2,
                    "entry_price": 50,
                    "entry_fee": 0.10,
                    "stop_price": 45,
                    "risk_budget": 10,
                    "opened_at": "2026-11-15T10:01:00Z",
                }
            },
            "history": state_after_close["history"],
        }
        second_report = build_legacy_paper_report(
            state_with_open_position, {"BTC/USDT": 55}
        )
        second = build_report_snapshot(
            second_report, "2026-11-15T10:01:00Z", "integration-002"
        )

        history = append_report_snapshot([first], second)
        payload = serialize_report_history(history)
        restored = deserialize_report_history(payload)
        dashboard = build_report_dashboard_model(restored)

        self.assertEqual(dashboard["snapshot_count"], 2)
        self.assertEqual(dashboard["latest_metrics"]["equity_usdt"], "1019.69")
        self.assertEqual(dashboard["latest_metrics"]["total_pnl_usdt"], "19.69")
        self.assertEqual(second_report["realized_pnl_usdt"], "9.79")
        self.assertEqual(second_report["unrealized_pnl_usdt"], "9.9")
        self.assertEqual(second_report["fees_paid_usdt"], "0.31")
        self.assertEqual(second_report["trade_count"], 1)
        self.assertEqual(second_report["buy_count"], 2)
        self.assertEqual(second_report["sell_count"], 1)
        self.assertEqual(dashboard["latest_assets"][0]["asset"], "BTC")
        self.assertEqual(dashboard["latest_assets"][0]["market_value_usdt"], "110")
        self.assertEqual(dashboard["equity_drawdown"]["max_drawdown_usdt"], "0")
        self.assertIn("integration-002", export_report_history_csv(restored))

    def test_open_positions_require_explicit_marks(self):
        state = {
            "initial_balance": 1000,
            "cash_usdt": 899.9,
            "positions": {
                "BTC/USDT": {
                    "quantity": 1,
                    "entry_price": 100,
                    "entry_fee": 0.1,
                }
            },
            "history": [],
        }
        with self.assertRaisesRegex(ValueError, "marks"):
            build_legacy_paper_report(state, {})


if __name__ == "__main__":
    unittest.main()
