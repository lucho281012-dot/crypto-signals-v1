"""Verify official Kraken OHLCVT split-archive parts before reassembly.

The tool never downloads data. It requires the official SHA256SUMS file and
validates every expected part before writing the combined ZIP.
"""
import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path

PART_NAMES = tuple(f"Kraken_OHLCVT_Full.zip.part{i:02d}" for i in range(5))
COMBINED_SHA256 = "bc273e9027470b07d790a7fa4df9bb43f0dfc527c20c6ecae48402e123e7b1c7"
CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")


def parse_checksum_file(path):
    """Parse sha256sum-style lines, preserving only safe basenames."""
    checksums = {}
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            match = CHECKSUM_RE.fullmatch(line)
            if not match:
                raise ValueError(f"Línea {line_number}: formato SHA-256 inválido")
            digest, filename = match.groups()
            if Path(filename).name != filename or filename in {".", ".."}:
                raise ValueError(f"Línea {line_number}: nombre de archivo no seguro")
            if filename in checksums:
                raise ValueError(f"Línea {line_number}: checksum duplicado")
            checksums[filename] = digest.lower()
    return checksums


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_parts(parts_dir, checksum_file, required_names=PART_NAMES):
    """Verify all required parts; fail closed on missing or invalid checksums."""
    parts_dir = Path(parts_dir)
    checksums = parse_checksum_file(checksum_file)
    results = []
    for name in required_names:
        expected = checksums.get(name)
        if expected is None:
            raise ValueError(f"Falta checksum publicado para {name}")
        path = parts_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        results.append({
            "file": name,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "valid": actual == expected,
            "size_bytes": path.stat().st_size,
        })
    invalid = [item["file"] for item in results if not item["valid"]]
    if invalid:
        raise ValueError("Checksum incorrecto para: " + ", ".join(invalid))
    return results


def assemble_verified_parts(
    parts_dir,
    checksum_file,
    output_path,
    expected_combined_sha256=COMBINED_SHA256,
    required_names=PART_NAMES,
):
    """Verify all parts first, then atomically assemble and verify the ZIP."""
    parts_dir = Path(parts_dir)
    output_path = Path(output_path)
    if output_path.exists() and any(
        output_path.resolve() == (parts_dir / name).resolve()
        for name in required_names
    ):
        raise ValueError("El ZIP de salida no puede sobrescribir una parte")
    results = verify_parts(parts_dir, checksum_file, required_names)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=output_path.name + ".", suffix=".partial",
        dir=str(output_path.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with temp_path.open("wb") as target:
            for name in required_names:
                with (parts_dir / name).open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        combined_sha = sha256_file(temp_path)
        if expected_combined_sha256 and combined_sha.lower() != expected_combined_sha256.lower():
            raise ValueError(
                "SHA-256 del ZIP reensamblado no coincide: " + combined_sha
            )
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return {
        "output": str(output_path),
        "combined_sha256": combined_sha,
        "expected_combined_sha256": expected_combined_sha256,
        "parts": results,
        "verified": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Verifica checksums oficiales y reensambla Kraken OHLCVT Full"
    )
    parser.add_argument("parts_dir", help="Carpeta con los cinco archivos .part00-.part04")
    parser.add_argument("checksum_file", help="Archivo oficial SHA256SUMS descargado de Kraken")
    parser.add_argument("output_zip", help="Ruta del ZIP reensamblado")
    parser.add_argument(
        "--skip-combined-check",
        action="store_true",
        help="No comparar el SHA-256 final con el checksum publicado del ZIP",
    )
    args = parser.parse_args()
    report = assemble_verified_parts(
        args.parts_dir,
        args.checksum_file,
        args.output_zip,
        expected_combined_sha256=None if args.skip_combined_check else COMBINED_SHA256,
    )
    print("Verificación completada:", report["combined_sha256"])
    for item in report["parts"]:
        print(f'{item["file"]}: OK ({item["size_bytes"]} bytes)')


if __name__ == "__main__":
    main()
