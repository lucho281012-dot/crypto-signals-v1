import struct
import unittest

from kraken_zip64_range_inspector import (
    ArchiveInspectionError, Part, RangeArchive, PART_NAMES,
    inspect_with_reader, _parse_zip64_directory,
)

def make_zip64_archive(names):
    local = bytearray()
    central = bytearray()
    for name in names:
        encoded = name.encode("utf-8")
        local_offset = len(local)
        payload = b""
        local += struct.pack(
            "<4s5H3I2H", b"PK\x03\x04", 20, 0x0800, 0, 0, 0,
            0, len(payload), len(payload), len(encoded), 0
        ) + encoded + payload
        central += struct.pack(
            "<4s6H3I5H2I", b"PK\x01\x02", 20, 20, 0x0800, 0, 0, 0,
            0, len(payload), len(payload), len(encoded), 0, 0, 0, 0, 0, local_offset
        ) + encoded
    cd_offset = len(local)
    cd_size = len(central)
    zip64_offset = cd_offset + cd_size
    zip64 = struct.pack(
        "<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0,
        len(names), len(names), cd_size, cd_offset
    )
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, zip64_offset, 1)
    eocd = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF,
                       0xFFFFFFFF, 0xFFFFFFFF, 0)
    return bytes(local + central) + zip64 + locator + eocd


class Zip64RangeInspectorTests(unittest.TestCase):
    TARGETS = [
        "XBTUSDT_5.csv", "XBTUSDT_15.csv",
        "ETHUSDT_5.csv", "ETHUSDT_15.csv",
        "SOLUSDT_5.csv", "SOLUSDT_15.csv",
    ]

    def test_finds_all_six_exact_targets_without_payload_download(self):
        archive = make_zip64_archive(self.TARGETS)
        report = inspect_with_reader(lambda o, n: archive[o:o+n], len(archive))
        self.assertTrue(report["all_six_unique"])
        self.assertEqual(set(report["target_matches"]), set(self.TARGETS))
        self.assertEqual(report["member_payload_bytes_downloaded"], 0)

    def test_reports_missing_target_without_claiming_success(self):
        archive = make_zip64_archive(self.TARGETS[:-1])
        report = inspect_with_reader(lambda o, n: archive[o:o+n], len(archive))
        self.assertFalse(report["all_six_unique"])
        self.assertEqual(report["missing_targets"], ["SOLUSDT_15.csv"])

    def test_duplicate_target_is_ambiguous(self):
        archive = make_zip64_archive(self.TARGETS + ["folder/XBTUSDT_5.csv"])
        report = inspect_with_reader(lambda o, n: archive[o:o+n], len(archive))
        self.assertFalse(report["all_six_unique"])
        self.assertEqual(report["ambiguous_targets"], ["XBTUSDT_5.csv"])

    def test_rejects_missing_zip64_locator(self):
        archive = bytearray(make_zip64_archive(self.TARGETS))
        archive[-42:-22] = b"\x00" * 20
        with self.assertRaises(ArchiveInspectionError):
            _parse_zip64_directory(lambda o, n: bytes(archive[o:o+n]), len(archive))

    def test_rejects_true_multidisk_zip64_layout(self):
        archive = bytearray(make_zip64_archive(self.TARGETS))
        locator_offset = len(archive) - 42
        struct.pack_into("<I", archive, locator_offset + 4, 1)
        with self.assertRaises(ArchiveInspectionError):
            _parse_zip64_directory(lambda o, n: bytes(archive[o:o+n]), len(archive))

    def test_virtual_range_can_cross_split_part_boundary(self):
        raw = b"abcdefghij"
        sizes = [2, 2, 2, 2, 2]
        starts = [0, 2, 4, 6, 8]
        def fetch(index, start, end):
            return raw[starts[index] + start:starts[index] + end + 1]
        parts = [Part(PART_NAMES[i], sizes[i]) for i in range(5)]
        reader = RangeArchive(parts, fetch)
        self.assertEqual(reader.read_at(1, 8), b"bcdefghi")
        self.assertEqual(reader.bytes_read, 8)

    def test_rejects_directory_above_safety_cap(self):
        archive = bytearray(make_zip64_archive(self.TARGETS))
        # ZIP64 EOCD starts immediately before locator and standard EOCD.
        zip64_offset = len(archive) - 98
        struct.pack_into("<Q", archive, zip64_offset + 40, 64 * 1024 * 1024 + 1)
        with self.assertRaises(ArchiveInspectionError):
            _parse_zip64_directory(lambda o, n: bytes(archive[o:o+n]), len(archive))


if __name__ == "__main__":
    unittest.main()
