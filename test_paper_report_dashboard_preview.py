import copy
import unittest

from paper_report_dashboard_preview import build_dashboard_preview


def report(equity, cash, pnl, return_pct):
    return {
        "quote_currency": "USDT", "initial_cash_usdt": "100",
        "cash_usdt": str(cash), "market_value_usdt": "0",
        "equity_usdt": str(equity), "total_pnl_usdt": str(pnl),
        "total_return_pct": str(return_pct), "realized_pnl_usdt": str(pnl),
        "unrealized_pnl_usdt": "0", "fees_paid_usdt": "0",
        "trade_count": 3, "buy_count": 3, "sell_count": 3,
        "open_position_count": 0, "positions": {},
    }


class DashboardPreviewTests(unittest.TestCase):
    def test_builds_dashboard_preview_in_memory(self):
        result = build_dashboard_preview(
            report("99.5", "99.5", "-0.5", "-0.5"),
            "2026-11-15T16:00:00Z", "paper-preview-001",
        )
        self.assertEqual(result["dashboard"]["snapshot_count"], 1)
        self.assertEqual(result["dashboard"]["latest_metrics"]["equity_usdt"], "99.5")
        self.assertEqual(result["dashboard"]["summary"]["latest_total_pnl_usdt"], "-0.5")
        self.assertEqual(result["snapshot"]["snapshot_id"], "paper-preview-001")
        self.assertEqual(result["history"][0]["snapshot_id"], "paper-preview-001")

    def test_appends_to_supplied_history_without_mutating_it(self):
        original = build_dashboard_preview(
            report("100", "100", "0", "0"),
            "2026-11-15T15:00:00Z", "paper-preview-000",
        )["history"]
        before = copy.deepcopy(original)
        result = build_dashboard_preview(
            report("99.5", "99.5", "-0.5", "-0.5"),
            "2026-11-15T16:00:00Z", "paper-preview-001", original,
        )
        self.assertEqual(original, before)
        self.assertEqual(result["dashboard"]["snapshot_count"], 2)
        self.assertEqual(result["dashboard"]["equity_drawdown"]["max_drawdown_usdt"], "-0.5")

    def test_rejects_duplicate_snapshot_id(self):
        history = build_dashboard_preview(
            report("100", "100", "0", "0"),
            "2026-11-15T15:00:00Z", "same-id",
        )["history"]
        with self.assertRaisesRegex(ValueError, "duplicate snapshot_id"):
            build_dashboard_preview(
                report("99", "99", "-1", "-1"),
                "2026-11-15T16:00:00Z", "same-id", history,
            )

    def test_rejects_non_increasing_timestamp(self):
        history = build_dashboard_preview(
            report("100", "100", "0", "0"),
            "2026-11-15T15:00:00Z", "first",
        )["history"]
        with self.assertRaisesRegex(ValueError, "later"):
            build_dashboard_preview(
                report("99", "99", "-1", "-1"),
                "2026-11-15T14:59:00Z", "second", history,
            )


if __name__ == "__main__":
    unittest.main()
