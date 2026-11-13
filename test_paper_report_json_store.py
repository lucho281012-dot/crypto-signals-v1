import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_report_history import build_report_snapshot
from paper_report_json_store import (
    load_report_history,
    recover_report_history,
    save_report_history,
)


class PaperReportJsonStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "reports" / "history.json"
        self.first = build_report_snapshot(
            {"equity_usdt": "1000", "quote_currency": "USDT"},
            "2026-11-13T10:00:00Z",
            "snap-001",
        )
        self.second = build_report_snapshot(
            {"equity_usdt": "1010", "quote_currency": "USDT"},
            "2026-11-13T10:01:00Z",
            "snap-002",
        )

    def test_save_and_load_creates_directory_and_round_trips(self):
        self.assertEqual(save_report_history(self.path, [self.first]), 1)
        self.assertEqual(load_report_history(self.path), [self.first])

    def test_second_save_keeps_append_only_prefix_and_backup(self):
        save_report_history(self.path, [self.first])
        self.assertEqual(save_report_history(self.path, [self.first, self.second]), 2)
        backup = self.path.with_name(self.path.name + ".bak")
        self.assertTrue(backup.exists())
        self.assertEqual(json.loads(backup.read_text("utf-8")), [self.first])
        self.assertEqual(load_report_history(self.path), [self.first, self.second])

    def test_refuses_to_truncate_or_rewrite_existing_history(self):
        save_report_history(self.path, [self.first])
        changed = dict(self.first, report={"equity_usdt": "999"})
        with self.assertRaisesRegex(ValueError, "preserve all existing"):
            save_report_history(self.path, [changed])
        with self.assertRaisesRegex(ValueError, "preserve all existing"):
            save_report_history(self.path, [])

    def test_refuses_to_overwrite_corrupt_primary(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid report history"):
            save_report_history(self.path, [self.first])
        self.assertEqual(self.path.read_text("utf-8"), "{broken")

    def test_explicit_recovery_restores_previous_valid_backup(self):
        save_report_history(self.path, [self.first])
        save_report_history(self.path, [self.first, self.second])
        self.path.write_text("{corrupt", encoding="utf-8")
        recovered = recover_report_history(self.path)
        self.assertEqual(recovered, [self.first])
        self.assertEqual(load_report_history(self.path), [self.first])
        self.assertTrue(self.path.with_name(self.path.name + ".bak").exists())

    def test_recovery_rejects_invalid_backup_without_changing_primary(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("primary", encoding="utf-8")
        self.path.with_name(self.path.name + ".bak").write_text("{bad", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid report history"):
            recover_report_history(self.path)
        self.assertEqual(self.path.read_text("utf-8"), "primary")

    def test_load_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_report_history(self.path)

    def test_save_rejects_invalid_history_before_writing(self):
        with self.assertRaisesRegex(ValueError, "list"):
            save_report_history(self.path, {})
        self.assertFalse(self.path.exists())

    def test_refuses_paper_state_filename(self):
        forbidden = Path(self.temp_dir.name) / "paper_state.json"
        with self.assertRaisesRegex(ValueError, "refusing"):
            save_report_history(forbidden, [self.first])

    def test_atomic_write_failure_does_not_create_partial_primary(self):
        with patch("paper_report_json_store.os.replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaisesRegex(OSError, "simulated"):
                save_report_history(self.path, [self.first])
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_invalid_utf8_primary_is_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            save_report_history(self.path, [self.first])
        self.assertEqual(self.path.read_bytes(), b"\xff\xfe")

    def test_backup_is_not_created_for_first_save(self):
        save_report_history(self.path, [self.first])
        self.assertFalse(self.path.with_name(self.path.name + ".bak").exists())


if __name__ == "__main__":
    unittest.main()
