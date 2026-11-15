import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from kraken_archive_inspector import inspect_kraken_archive


class KrakenArchiveInspectorTests(unittest.TestCase):
    def make_archive(self, entries):
        handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        handle.close()
        path = Path(handle.name)
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in entries:
                archive.writestr(name, content)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_finds_exact_native_market_and_timeframe_members(self):
        path = self.make_archive([
            ("MANIFEST.json", json.dumps({"version": "unknown-schema"})),
            ("spot/XBTUSDT_5.csv", "csv-data"),
            ("spot/XBTUSDT_15.csv", "csv-data"),
            ("spot/ETHUSDT_5.csv", "csv-data"),
            ("spot/ETHUSDT_15.csv", "csv-data"),
            ("spot/SOLUSDT_5.csv", "csv-data"),
            ("spot/SOLUSDT_15.csv", "csv-data"),
            ("spot/XBTUSD_5.csv", "wrong quote"),
            ("spot/XBTUSDT_60.csv", "wrong timeframe"),
        ])
        report = inspect_kraken_archive(path)
        self.assertEqual(report["manifest"]["status"], "parsed")
        self.assertFalse(report["manifest"]["schema_interpreted"])
        self.assertTrue(all(item["status"] == "unique" for item in report["matches"]))
        self.assertFalse(report["csv_data_extracted"])

    def test_missing_exact_pair_is_not_substituted_with_usd_pair(self):
        path = self.make_archive([
            ("XBTUSD_5.csv", "wrong quote"),
            ("ETHUSDT_5.csv", "csv-data"),
        ])
        report = inspect_kraken_archive(path, ["XBTUSDT"], [5])
        self.assertEqual(report["matches"][0]["status"], "missing")
        self.assertEqual(report["matches"][0]["matches"], [])

    def test_duplicate_exact_basenames_are_ambiguous(self):
        path = self.make_archive([
            ("part-a/XBTUSDT_5.csv", "a"),
            ("part-b/XBTUSDT_5.csv", "b"),
        ])
        report = inspect_kraken_archive(path, ["XBTUSDT"], [5])
        self.assertEqual(report["matches"][0]["status"], "ambiguous")
        self.assertEqual(report["matches"][0]["candidate_count"], 2)

    def test_manifest_is_reported_without_assuming_its_schema(self):
        path = self.make_archive([
            ("MANIFEST.json", json.dumps(["format", "metadata"])),
            ("XBTUSDT_5.csv", "csv-data"),
        ])
        report = inspect_kraken_archive(path, ["XBTUSDT"], [5])
        self.assertEqual(report["manifest"]["json_type"], "array")
        self.assertEqual(report["manifest"]["top_level_keys"], [])
        self.assertFalse(report["manifest"]["schema_interpreted"])

    def test_rejects_invalid_market_ids_and_timeframes(self):
        path = self.make_archive([("XBTUSDT_5.csv", "csv-data")])
        with self.assertRaises(ValueError):
            inspect_kraken_archive(path, ["XBT/USDT"], [5])
        with self.assertRaises(ValueError):
            inspect_kraken_archive(path, ["XBTUSDT"], [True])


if __name__ == "__main__":
    unittest.main()
