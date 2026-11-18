import json
import tempfile
import unittest
from pathlib import Path

from import_kraken_ohlcvt import import_csv


class KrakenOHLCVTImportTests(unittest.TestCase):
    def test_import_converts_epoch_seconds_and_merges_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "XBTUSDT_5.csv"
            source.write_text(
                "300,10,11,9,10.5,12,3\n"
                "600,10.5,12,10,11.5,13,4\n",
                encoding="utf-8",
            )
            result = import_csv(source, "BTC/USDT", "5m", root / "out")
            target = root / "out" / "BTC_USDT_5m.jsonl"
            rows = [json.loads(line) for line in target.read_text().splitlines()]
            self.assertEqual([row["timestamp"] for row in rows], [300000, 600000])
            self.assertEqual(result["rows_read"], 2)
            self.assertEqual(result["total_rows"], 2)

    def test_import_rejects_bad_csv_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bad.csv"
            source.write_text("300,10,9,8,10,1,1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_csv(source, "BTC/USDT", "5m", root / "out")

    def test_import_rejects_fractional_epoch_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bad.csv"
            source.write_text("300.5,10,11,9,10,1,1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_csv(source, "BTC/USDT", "5m", root / "out")


if __name__ == "__main__":
    unittest.main()
