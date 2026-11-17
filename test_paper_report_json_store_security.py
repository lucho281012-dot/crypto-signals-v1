"""Security regression tests for report-history path validation."""
import tempfile
import unittest
from pathlib import Path

from paper_report_history import build_report_snapshot
from paper_report_json_store import load_report_history, save_report_history


class PaperReportJsonStorePathSecurityTests(unittest.TestCase):
    def test_rejects_case_variant_of_protected_paper_state_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            protected = Path(directory) / "PAPER_STATE.JSON"
            snapshot = build_report_snapshot(
                {"equity_usdt": "1000"},
                "2026-11-15T10:00:00Z",
                "security-001",
            )
            with self.assertRaisesRegex(ValueError, "paper trading state"):
                save_report_history(protected, [snapshot])

    def test_rejects_symlink_alias_to_paper_state_for_reads_and_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = root / "paper_state.json"
            protected.write_text('{"do_not_touch": true}', encoding="utf-8")
            alias = root / "report-history.json"
            alias.symlink_to(protected)

            snapshot = build_report_snapshot(
                {"equity_usdt": "1000"},
                "2026-11-15T10:00:00Z",
                "security-002",
            )
            with self.assertRaisesRegex(ValueError, "paper trading state"):
                load_report_history(alias)
            with self.assertRaisesRegex(ValueError, "paper trading state"):
                save_report_history(alias, [snapshot])
            self.assertEqual(
                protected.read_text("utf-8"),
                '{"do_not_touch": true}',
            )


if __name__ == "__main__":
    unittest.main()
