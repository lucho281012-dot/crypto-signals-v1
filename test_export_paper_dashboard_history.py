"""Tests for the read-only paper dashboard history exporter."""
import io
import json
from pathlib import Path
import tempfile
import unittest

from export_paper_dashboard_history import export_history_json, main
from paper_report_history import build_report_snapshot, serialize_report_history
from paper_report_json_store import save_report_history


class ExportPaperDashboardHistoryTests(unittest.TestCase):
    def _history(self):
        report = {
            "quote_currency": "USDT",
            "initial_cash_usdt": "1000.00",
            "equity_usdt": "1000.00",
            "cash_usdt": "1000.00",
            "market_value_usdt": "0.00",
            "total_pnl_usdt": "0.00",
            "total_return_pct": "0.00",
            "positions": {},
        }
        return [
            build_report_snapshot(
                report, "2026-11-13T09:00:00-06:00", "snapshot-001"
            )
        ]

    def test_exports_valid_history_as_dashboard_import_json(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper_report_history.json"
            history = self._history()
            save_report_history(source, history)

            payload = export_history_json(source)

            self.assertEqual(json.loads(payload), history)
            self.assertEqual(payload, serialize_report_history(history))

    def test_refuses_operational_paper_state_filename(self):
        with self.assertRaisesRegex(ValueError, "paper_state.json"):
            export_history_json("paper_state.json")

    def test_cli_writes_json_to_stdout_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper_report_history.json"
            history = self._history()
            save_report_history(source, history)
            before = source.read_bytes()
            stdout = io.StringIO()
            stderr = io.StringIO()

            result = main(["--input", str(source)], stdout, stderr)

            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.getvalue()), history)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(source.read_bytes(), before)

    def test_cli_rejects_missing_history_file(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        result = main(["--input", "missing-paper-report-history.json"], stdout, stderr)

        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Export refused", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
