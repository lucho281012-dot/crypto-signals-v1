import csv
import tempfile
import unittest
from pathlib import Path

from kraken_ohlcvt import load_kraken_ohlcvt_csv


def write_rows(rows):
    temp = tempfile.NamedTemporaryFile(
        mode="w", newline="", encoding="utf-8", suffix=".csv", delete=False
    )
    with temp:
        writer = csv.writer(temp)
        writer.writerows(rows)
    return Path(temp.name)


class KrakenOHLCVTTests(unittest.TestCase):
    def test_loads_headerless_rows_and_converts_seconds_to_milliseconds(self):
        path = write_rows([
            [600, 100, 102, 99, 101, 12.5, 8],
            [900, 101, 103, 100, 102, 10, 7],
        ])
        try:
            result = load_kraken_ohlcvt_csv(path, 5)
            self.assertEqual(result["candles"][0]["timestamp"], 600000)
            self.assertEqual(result["candles"][1]["volume"], 10)
            self.assertEqual(result["metadata"]["row_count"], 2)
            self.assertEqual(len(result["metadata"]["source_sha256"]), 64)
            self.assertFalse(result["metadata"]["gaps_filled"])
        finally:
            path.unlink()

    def test_rejects_gaps_by_default_and_reports_without_filling_when_allowed(self):
        path = write_rows([
            [600, 100, 102, 99, 101, 12.5, 8],
            [1200, 101, 103, 100, 102, 10, 7],
        ])
        try:
            with self.assertRaisesRegex(ValueError, "intervalos sin operaciones"):
                load_kraken_ohlcvt_csv(path, 5)
            result = load_kraken_ohlcvt_csv(path, 5, require_contiguous=False)
            self.assertEqual(result["metadata"]["missing_intervals"], 1)
            self.assertEqual(len(result["candles"]), 2)
            self.assertFalse(result["metadata"]["gaps_filled"])
        finally:
            path.unlink()

    def test_rejects_duplicate_or_unsorted_timestamps(self):
        path = write_rows([
            [600, 100, 102, 99, 101, 12.5, 8],
            [600, 101, 103, 100, 102, 10, 7],
        ])
        try:
            with self.assertRaisesRegex(ValueError, "duplicados o desordenados"):
                load_kraken_ohlcvt_csv(path, 5)
        finally:
            path.unlink()

    def test_rejects_bad_ohlc(self):
        path = write_rows([[600, 100, 98, 99, 101, 12.5, 8]])
        try:
            with self.assertRaisesRegex(ValueError, "OHLC inconsistente"):
                load_kraken_ohlcvt_csv(path, 5)
        finally:
            path.unlink()

    def test_rejects_wrong_column_count_and_unaligned_timestamp(self):
        path = write_rows([[600, 100, 102, 99, 101, 12.5]])
        try:
            with self.assertRaisesRegex(ValueError, "7 columnas"):
                load_kraken_ohlcvt_csv(path, 5)
        finally:
            path.unlink()

        path = write_rows([[601, 100, 102, 99, 101, 12.5, 8]])
        try:
            with self.assertRaisesRegex(ValueError, "no alineado"):
                load_kraken_ohlcvt_csv(path, 5)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
