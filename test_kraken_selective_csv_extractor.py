import tempfile
import unittest
import zlib
from pathlib import Path

from kraken_selective_csv_extractor import (
    SelectiveExtractionError, extract_member,
)


def make_member(name="XBTUSDT_5.csv", payload=b"1700000100,100,101,99,100.5,2.5,3\n"):
    compressor = zlib.compressobj(level=6, wbits=-15)
    compressed = compressor.compress(payload) + compressor.flush()
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    flags = 0x0800
    name_bytes = name.encode("utf-8")
    header = (
        b"PK\x03\x04"
        + (20).to_bytes(2, "little")
        + flags.to_bytes(2, "little")
        + (8).to_bytes(2, "little")
        + b"\x00" * 4
        + crc.to_bytes(4, "little")
        + len(compressed).to_bytes(4, "little")
        + len(payload).to_bytes(4, "little")
        + len(name_bytes).to_bytes(2, "little")
        + (0).to_bytes(2, "little")
        + name_bytes
    )
    archive_bytes = header + compressed
    member = {
        "name": name,
        "compressed_size": len(compressed),
        "uncompressed_size": len(payload),
        "compression_method": 8,
        "crc32": f"{crc:08x}",
        "local_header_offset": 0,
        "disk_start": 0,
        "encrypted": False,
        "flags": flags,
        "central_directory_offset": len(archive_bytes) + 100,
    }
    return archive_bytes, member, payload


class SelectiveCSVExtractorTests(unittest.TestCase):
    def extract(self, archive, member, name="XBTUSDT_5.csv"):
        def read_at(offset, length):
            return archive[offset:offset + length]
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        output = Path(temp.name) / name
        result = extract_member(read_at, member, name, output)
        return result, output.read_bytes()

    def test_extracts_raw_deflate_and_verifies_crc_and_sizes(self):
        archive, member, payload = make_member()
        result, actual = self.extract(archive, member)
        self.assertEqual(actual, payload)
        self.assertEqual(result["status"], "crc_and_size_verified")
        self.assertEqual(result["uncompressed_bytes"], len(payload))

    def test_rejects_crc_mismatch_and_removes_partial_output(self):
        archive, member, _ = make_member()
        member["crc32"] = "00000000"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bad.csv"
            with self.assertRaisesRegex(SelectiveExtractionError, "CRC32 mismatch"):
                extract_member(lambda o, n: archive[o:o+n], member, "XBTUSDT_5.csv", output)
            self.assertFalse(output.exists())

    def test_rejects_local_filename_mismatch(self):
        archive, member, _ = make_member(name="wrong.csv")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(SelectiveExtractionError, "local filename mismatch"):
                extract_member(lambda o, n: archive[o:o+n], member, "XBTUSDT_5.csv", Path(temp) / "x.csv")

    def test_rejects_local_central_flag_mismatch(self):
        archive, member, _ = make_member()
        member["flags"] = 0
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(SelectiveExtractionError, "flags disagree"):
                extract_member(lambda o, n: archive[o:o+n], member, "XBTUSDT_5.csv", Path(temp) / "x.csv")

    def test_rejects_uncompressed_size_over_safety_limit(self):
        archive, member, _ = make_member()
        member["uncompressed_size"] = 50 * 1024 * 1024 + 1
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(SelectiveExtractionError, "uncompressed size exceeds"):
                extract_member(lambda o, n: archive[o:o+n], member, "XBTUSDT_5.csv", Path(temp) / "x.csv")


if __name__ == "__main__":
    unittest.main()
