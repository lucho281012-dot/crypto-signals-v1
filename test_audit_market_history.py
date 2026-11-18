import json
import tempfile
import unittest
from pathlib import Path

from audit_market_history import audit_file
from market_history_collector import TIMEFRAMES


class TemporalAuditTests(unittest.TestCase):
    def test_reports_gap_without_filling_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candles.jsonl"
            rows = [
                {"timestamp": 0, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
                {"timestamp": 600_000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            result = audit_file(path, TIMEFRAMES["5m"])
            self.assertTrue(result["valid"])
            self.assertEqual(result["rows_read"], 2)
            self.assertEqual(result["gap_count"], 1)
            self.assertEqual(result["first_gap"]["missing_intervals_estimate"], 1)

    def test_rejects_misaligned_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candles.jsonl"
            row = {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1}
            path.write_text(json.dumps(row) + "\n")
            result = audit_file(path, TIMEFRAMES["5m"])
            self.assertFalse(result["valid"])
            self.assertIn("Timestamp not aligned", result["errors"][0]["error"])

    def test_detects_non_increasing_order_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candles.jsonl"
            rows = [
                {"timestamp": 300_000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
                {"timestamp": 0, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
                {"timestamp": 300_000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            result = audit_file(path, TIMEFRAMES["5m"])
            self.assertFalse(result["valid"])
            self.assertEqual(result["duplicate_rows"], 1)
            self.assertTrue(any(item["error"] == "timestamps_not_strictly_increasing" for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
