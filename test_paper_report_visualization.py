import unittest

from paper_report_history import build_report_snapshot
from paper_report_visualization import build_report_chart_data


class PaperReportVisualizationTests(unittest.TestCase):
    def _snapshot(self, snapshot_id, captured_at, equity, btc_value="0", eth_value=None):
        positions = {}
        if btc_value is not None:
            positions["BTC"] = {"market_value_usdt": btc_value}
        if eth_value is not None:
            positions["ETH"] = {"market_value_usdt": eth_value}
        report = {
            "equity_usdt": equity,
            "total_pnl_usdt": str(float(equity) - 1000),
            "total_return_pct": str((float(equity) - 1000) / 10),
            "cash_usdt": "800",
            "market_value_usdt": str(float(equity) - 800),
            "positions": positions,
        }
        return build_report_snapshot(report, captured_at, snapshot_id)

    def test_builds_chronological_portfolio_metric_series(self):
        history = [
            self._snapshot("s1", "2026-11-13T10:00:00Z", "1000"),
            self._snapshot("s2", "2026-11-13T11:00:00Z", "1025.5"),
        ]
        data = build_report_chart_data(history)
        self.assertEqual(data["snapshot_count"], 2)
        self.assertEqual(data["timestamps"], ["2026-11-13T10:00:00Z", "2026-11-13T11:00:00Z"])
        self.assertEqual([p["value"] for p in data["series"]["equity_usdt"]], ["1000", "1025.5"])
        self.assertEqual(data["series"]["equity_usdt"][1]["snapshot_id"], "s2")

    def test_asset_series_union_and_zero_for_absent_position(self):
        history = [
            self._snapshot("s1", "2026-11-13T10:00:00Z", "1000", btc_value="200"),
            self._snapshot("s2", "2026-11-13T11:00:00Z", "1010", btc_value=None, eth_value="210"),
        ]
        data = build_report_chart_data(history)
        self.assertEqual(set(data["asset_market_value_usdt"]), {"BTC", "ETH"})
        self.assertEqual([p["value"] for p in data["asset_market_value_usdt"]["BTC"]], ["200", "0"])
        self.assertEqual([p["value"] for p in data["asset_market_value_usdt"]["ETH"]], ["0", "210"])

    def test_empty_history_returns_empty_series(self):
        data = build_report_chart_data([])
        self.assertEqual(data["snapshot_count"], 0)
        self.assertEqual(data["timestamps"], [])
        self.assertEqual(data["series"]["equity_usdt"], [])
        self.assertEqual(data["asset_market_value_usdt"], {})

    def test_rejects_missing_required_metric(self):
        snapshot = build_report_snapshot(
            {"equity_usdt": "1000", "positions": {}},
            "2026-11-13T10:00:00Z",
            "s1",
        )
        with self.assertRaisesRegex(ValueError, "total_pnl_usdt"):
            build_report_chart_data([snapshot])

    def test_rejects_non_finite_metric(self):
        snapshot = self._snapshot("s1", "2026-11-13T10:00:00Z", "1000")
        snapshot["report"]["equity_usdt"] = "NaN"
        with self.assertRaisesRegex(ValueError, "finite"):
            build_report_chart_data([snapshot])

    def test_rejects_invalid_position_market_value(self):
        snapshot = self._snapshot("s1", "2026-11-13T10:00:00Z", "1000")
        snapshot["report"]["positions"]["BTC"] = {"market_value_usdt": "Infinity"}
        with self.assertRaisesRegex(ValueError, "finite"):
            build_report_chart_data([snapshot])

    def test_does_not_mutate_history(self):
        history = [self._snapshot("s1", "2026-11-13T10:00:00Z", "1000")]
        before = repr(history)
        build_report_chart_data(history)
        self.assertEqual(repr(history), before)

    def test_rejects_invalid_history(self):
        with self.assertRaisesRegex(ValueError, "list"):
            build_report_chart_data({})
        
if __name__ == "__main__":
    unittest.main()
