import json
import tempfile
import unittest
from pathlib import Path

from market_history_audit import audit_file


class MarketHistoryAuditTests(unittest.TestCase):
    def write_rows(self, directory, rows):
        path = Path(directory) / "candles.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def candle(self, timestamp):
        return {"timestamp": timestamp, "open": 10, "high": 12,
                "low": 9, "close": 11, "volume": 4}

    def test_valid_archive_reports_count_and_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_rows(directory, [self.candle(0), self.candle(600_000)])
            result = audit_file(path, 300_000)
            self.assertEqual(result["candles"], 2)
            self.assertEqual(result["gap_count"], 1)
            self.assertEqual(result["missing_intervals_estimate"], 1)

    def test_duplicate_timestamps_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_rows(directory, [self.candle(0), self.candle(0)])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                audit_file(path, 300_000)

    def test_unsorted_timestamps_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_rows(directory, [self.candle(300_000), self.candle(0)])
            with self.assertRaisesRegex(ValueError, "not sorted"):
                audit_file(path, 300_000)

    def test_invalid_ohlc_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.candle(0)
            row["high"] = 8
            path = self.write_rows(directory, [row])
            with self.assertRaisesRegex(ValueError, "high"):
                audit_file(path, 300_000)


if __name__ == "__main__":
    unittest.main()
