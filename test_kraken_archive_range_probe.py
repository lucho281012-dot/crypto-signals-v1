import unittest
from unittest.mock import patch
import kraken_archive_range_probe as probe

class Response:
    def __init__(self, status=200, headers=None):
        self.status, self.headers, self.closed = status, headers or {}, False
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def close(self): self.closed = True

class KrakenArchiveRangeProbeTests(unittest.TestCase):
    @patch.object(probe, "_request")
    def test_accepts_exact_one_byte_partial_content(self, request):
        head = Response(200, {"Content-Length": "1000", "Accept-Ranges": "bytes"})
        ranged = Response(206, {"Content-Range": "bytes 0-0/1000"})
        request.side_effect = [head, ranged]
        result = probe.probe_part(probe.PART_NAMES[0])
        self.assertTrue(result["head_ok"])
        self.assertEqual(result["content_length"], 1000)
        self.assertTrue(result["range_supported"])
        self.assertEqual(result["range_total"], 1000)
        self.assertTrue(ranged.closed)

    @patch.object(probe, "_request")
    def test_server_ignoring_range_is_not_read(self, request):
        head = Response(200, {"Content-Length": "10000000000"})
        ranged = Response(200, {"Content-Length": "10000000000"})
        request.side_effect = [head, ranged]
        result = probe.probe_part(probe.PART_NAMES[0])
        self.assertFalse(result["range_supported"])
        self.assertIn("ignored Range", result["error"])
        self.assertTrue(ranged.closed)

    @patch.object(probe, "_request")
    def test_rejects_malformed_content_range(self, request):
        request.side_effect = [Response(200, {}), Response(206, {"Content-Range": "bytes 1-1/1000"})]
        result = probe.probe_part(probe.PART_NAMES[0])
        self.assertFalse(result["range_supported"])
        self.assertIsNone(result["range_total"])

    def test_rejects_unknown_part_name(self):
        with self.assertRaises(ValueError):
            probe.probe_part("untrusted.zip")

    @patch.object(probe, "probe_part")
    def test_all_ranges_flag_requires_every_part(self, part_probe):
        part_probe.side_effect = [
            {"part": name, "range_supported": i != 2, "range_total": 100}
            for i, name in enumerate(probe.PART_NAMES)]
        report = probe.probe_all()
        self.assertFalse(report["all_ranges_supported"])
        self.assertFalse(report["safe_for_selective_range_retrieval"])
        self.assertEqual(report["downloaded_archive_bytes"], 0)

if __name__ == "__main__":
    unittest.main()
