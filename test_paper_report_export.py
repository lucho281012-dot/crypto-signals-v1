import csv
import io
import unittest

from paper_report_history import build_report_snapshot
from paper_report_export import (
    build_report_history_summary,
    export_report_history_csv,
)


class PaperReportExportTests(unittest.TestCase):
    def setUp(self):
        self.first = build_report_snapshot(
            {
                "quote_currency": "USDT",
                "equity_usdt": "1000.00",
                "total_pnl_usdt": "0",
                "total_return_pct": "0",
                "positions": {},
            },
            "2026-11-13T10:00:00Z",
            "snap-001",
        )
        self.second = build_report_snapshot(
            {
                "quote_currency": "USDT",
                "equity_usdt": "1025.50",
                "total_pnl_usdt": "25.50",
                "total_return_pct": "2.55",
                "positions": {"BTC": {"quantity": "0.01"}},
            },
            "2026-11-13T11:00:00Z",
            "snap-002",
        )

    def test_csv_export_has_header_and_one_row_per_snapshot(self):
        payload = export_report_history_csv([self.first, self.second])
        rows = list(csv.DictReader(io.StringIO(payload)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["snapshot_id"], "snap-001")
        self.assertEqual(rows[1]["equity_usdt"], "1025.50")
        self.assertEqual(rows[1]["positions_json"], '{"BTC":{"quantity":"0.01"}}')

    def test_csv_export_is_deterministic(self):
        history = [self.first, self.second]
        self.assertEqual(export_report_history_csv(history), export_report_history_csv(history))

    def test_csv_export_supports_empty_history(self):
        rows = list(csv.DictReader(io.StringIO(export_report_history_csv([]))))
        self.assertEqual(rows, [])

    def test_csv_export_rejects_invalid_history(self):
        with self.assertRaisesRegex(ValueError, "list"):
            export_report_history_csv({})

    def test_csv_export_neutralizes_formula_like_text_cells(self):
        snapshot = build_report_snapshot(
            {"quote_currency": "=HYPERLINK('bad')", "equity_usdt": "10",
             "total_pnl_usdt": "0", "total_return_pct": "0"},
            "2026-11-13T12:00:00Z",
            "=cmd",
        )
        rows = list(csv.DictReader(io.StringIO(export_report_history_csv([snapshot]))))
        self.assertEqual(rows[0]["snapshot_id"], "'=cmd")
        self.assertEqual(rows[0]["quote_currency"], "'=HYPERLINK('bad')")

    def test_summary_reports_first_latest_and_extreme_equity(self):
        summary = build_report_history_summary([self.first, self.second])
        self.assertEqual(summary["snapshot_count"], 2)
        self.assertEqual(summary["first_equity_usdt"], "1000.00")
        self.assertEqual(summary["latest_equity_usdt"], "1025.50")
        self.assertEqual(summary["equity_change_usdt"], "25.50")
        self.assertEqual(summary["highest_equity_usdt"], "1025.50")
        self.assertEqual(summary["lowest_equity_usdt"], "1000.00")
        self.assertEqual(summary["latest_total_pnl_usdt"], "25.50")
        self.assertEqual(summary["latest_total_return_pct"], "2.55")

    def test_summary_supports_empty_history(self):
        self.assertEqual(build_report_history_summary([])["snapshot_count"], 0)
        self.assertIsNone(build_report_history_summary([])["latest_equity_usdt"])

    def test_summary_rejects_missing_or_non_numeric_equity(self):
        invalid = build_report_snapshot(
            {"total_pnl_usdt": "0", "total_return_pct": "0"},
            "2026-11-13T12:00:00Z",
            "snap-invalid",
        )
        with self.assertRaisesRegex(ValueError, "equity_usdt"):
            build_report_history_summary([invalid])

    def test_summary_rejects_non_finite_equity(self):
        invalid = build_report_snapshot(
            {"equity_usdt": "NaN", "total_pnl_usdt": "0", "total_return_pct": "0"},
            "2026-11-13T12:00:00Z",
            "snap-nan",
        )
        with self.assertRaisesRegex(ValueError, "finite"):
            build_report_history_summary([invalid])

    def test_export_and_summary_do_not_mutate_history(self):
        history = [self.first, self.second]
        before = [dict(item) for item in history]
        export_report_history_csv(history)
        build_report_history_summary(history)
        self.assertEqual(history, before)


if __name__ == "__main__":
    unittest.main()
