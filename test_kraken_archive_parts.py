import hashlib
import tempfile
import unittest
from pathlib import Path

from kraken_archive_parts import assemble_verified_parts, verify_parts


class KrakenArchivePartsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.parts = self.root / "parts"
        self.parts.mkdir()
        self.names = ("part00", "part01", "part02")
        self.contents = {}
        for index, name in enumerate(self.names):
            content = f"sample-part-{index}".encode()
            self.contents[name] = content
            (self.parts / name).write_bytes(content)
        self.checksums = self.root / "SHA256SUMS"
        self.write_checksums()

    def tearDown(self):
        self.temp.cleanup()

    def write_checksums(self):
        lines = []
        for name, content in self.contents.items():
            lines.append(f"{hashlib.sha256(content).hexdigest()}  {name}")
        self.checksums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_verifies_all_parts_before_assembly(self):
        results = verify_parts(self.parts, self.checksums, self.names)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(item["valid"] for item in results))

    def test_rejects_modified_part(self):
        (self.parts / "part01").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Checksum incorrecto"):
            verify_parts(self.parts, self.checksums, self.names)

    def test_rejects_missing_part(self):
        (self.parts / "part02").unlink()
        with self.assertRaises(FileNotFoundError):
            verify_parts(self.parts, self.checksums, self.names)

    def test_rejects_missing_checksum_entry(self):
        self.checksums.write_text(
            f"{hashlib.sha256(self.contents['part00']).hexdigest()}  part00\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Falta checksum"):
            verify_parts(self.parts, self.checksums, self.names)

    def test_assembles_in_order_and_checks_combined_hash(self):
        expected = b"".join(self.contents[name] for name in self.names)
        expected_sha = hashlib.sha256(expected).hexdigest()
        output = self.root / "assembled.zip"
        report = assemble_verified_parts(
            self.parts, self.checksums, output,
            expected_combined_sha256=expected_sha,
            required_names=self.names,
        )
        self.assertEqual(output.read_bytes(), expected)
        self.assertEqual(report["combined_sha256"], expected_sha)
        self.assertTrue(report["verified"])

    def test_does_not_leave_output_on_combined_hash_mismatch(self):
        output = self.root / "bad.zip"
        with self.assertRaisesRegex(ValueError, "ZIP reensamblado"):
            assemble_verified_parts(
                self.parts, self.checksums, output,
                expected_combined_sha256="0" * 64,
                required_names=self.names,
            )
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob("bad.zip.*.partial")), [])


if __name__ == "__main__":
    unittest.main()
