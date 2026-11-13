import copy
import unittest

from paper_report_history import build_report_snapshot
from paper_report_dashboard import build_report_dashboard_model


class PaperReportDashboardTests(unittest.TestCase):
    def snapshot(self, snapshot_id, captured_at, equity, cash, market_value,
                 pnl, return_pct, positions=None):
        report = {
            "quote_currency": "USDT",
            "equity_usdt": str(equity),
            "cash_usdt": str(cash),
            "market_value_usdt": str(market_value),
            "total_pnl_usdt": str(pnl),
            "total_return_pct": str(return_pct),
            "positions": positions or {},
        }
        return build_report_snapshot(report, captured_at, snapshot_id)

    def test_empty_history_has_empty_dashboard_state(self):
        model = build_report_dashboard_model([])
        self.assertEqual(model["snapshot_count"], 0)
        self.assertIsNone(model["latest_metrics"])
        self.assertEqual(model["latest_assets"], [])
        self.assertEqual(model["equity_drawdown"]["series"], [])
        self.assertIsNone(model["equity_drawdown"]["max_drawdown_pct"])

    def test_builds_latest_metrics_and_sorted_asset_allocation(self):
        history = [self.snapshot(
            "s1", "2026-11-13T10:00:00Z", "1000", "700", "300", "0", "0",
            {
                "ETH": {"market_value_usdt": "200"},
                "BTC": {"market_value_usdt": "100"},
            },
        )]
        model = build_report_dashboard_model(history)
        self.assertEqual(model["latest_metrics"]["equity_usdt"], "1000")
        self.assertEqual([item["asset"] for item in model["latest_assets"]], ["BTC", "ETH"])
        self.assertEqual(model["latest_assets"][0]["equity_weight_pct"], "10.0")
        self.assertEqual(model["latest_assets"][1]["equity_weight_pct"], "20.0")

    def test_drawdown_is_measured_from_running_equity_peak(self):
        history = [
            self.snapshot("s1", "2026-11-13T10:00:00Z", "1000", "800", "200", "0", "0"),
            self.snapshot("s2", "2026-11-13T11:00:00Z", "1200", "900", "300", "200", "20"),
            self.snapshot("s3", "2026-11-13T12:00:00Z", "1080", "800", "280", "80", "8"),
            self.snapshot("s4", "2026-11-13T13:00:00Z", "1140", "850", "290", "140", "14"),
        ]
        drawdown = build_report_dashboard_model(history)["equity_drawdown"]
        self.assertEqual(
            [point["drawdown_usdt"] for point in drawdown["series"]],
            ["0", "0", "-120", "-60"],
        )
        self.assertEqual(drawdown["max_drawdown_usdt"], "-120")
        self.assertEqual(drawdown["max_drawdown_pct"], "-10.0")

    def test_zero_or_negative_peak_has_no_percentage_drawdown(self):
        history = [
            self.snapshot("s1", "2026-11-13T10:00:00Z", "0", "0", "0", "-100", "-100"),
            self.snapshot("s2", "2026-11-13T11:00:00Z", "-5", "-5", "0", "-105", "-105"),
        ]
        drawdown = build_report_dashboard_model(history)["equity_drawdown"]
        self.assertEqual(drawdown["max_drawdown_usdt"], "-5")
        self.assertIsNone(drawdown["max_drawdown_pct"])
        self.assertIsNone(drawdown["series"][1]["drawdown_pct"])

    def test_rejects_non_finite_asset_value(self):
        history = [self.snapshot(
            "s1", "2026-11-13T10:00:00Z", "1000", "800", "200", "0", "0",
            {"BTC": {"market_value_usdt": "Infinity"}},
        )]
        with self.assertRaisesRegex(ValueError, "finite"):
            build_report_dashboard_model(history)

    def test_does_not_mutate_history(self):
        history = [
            self.snapshot("s1", "2026-11-13T10:00:00Z", "1000", "800", "200", "0", "0")
        ]
        before = copy.deepcopy(history)
        build_report_dashboard_model(history)
        self.assertEqual(history, before)


if __name__ == "__main__":
    unittest.main()
