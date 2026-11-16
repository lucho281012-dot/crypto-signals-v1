"""Selectively range-fetch, extract, and validate six Kraken OHLCVT CSV members.

No complete archive is downloaded or assembled. Compressed member bytes are read
in <=1 MiB HTTP ranges, decompressed with bounded output, and CRC/size checked.
Extracted CSVs live only in a temporary directory on the CI runner.
"""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import urllib.error
import zlib
from pathlib import Path
from typing import Any

from kraken_archive_range_probe import PART_NAMES, probe_part, _request
from kraken_ohlcvt import load_kraken_ohlcvt_csv
from kraken_gap_aware_segments import build_aligned_contiguous_segments
from historical_segment_backtest import backtest_segments
from historical_oos_validation import backtest_out_of_sample
from historical_5of5_walk_forward import backtest_5of5_walk_forward
from kraken_zip64_range_inspector import (
    ArchiveInspectionError, Part, RangeArchive, inspect_with_reader,
)

MAX_RANGE_BYTES = 1024 * 1024
MAX_COMPRESSED_MEMBER_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_MEMBER_BYTES = 50 * 1024 * 1024
MAX_DECOMPRESSED_CHUNK = 1024 * 1024
LOCAL_HEADER_SIG = b"PK\x03\x04"
EXPECTED_MEMBERS = {
    "XBTUSDT_5.csv": ("BTC/USDT", 5),
    "XBTUSDT_15.csv": ("BTC/USDT", 15),
    "ETHUSDT_5.csv": ("ETH/USDT", 5),
    "ETHUSDT_15.csv": ("ETH/USDT", 15),
    "SOLUSDT_5.csv": ("SOL/USDT", 5),
    "SOLUSDT_15.csv": ("SOL/USDT", 15),
}


class SelectiveExtractionError(RuntimeError):
    """Raised when a selected ZIP member fails structural or integrity checks."""


def _local_zip64_sizes(extra: bytes, need_uncompressed: bool, need_compressed: bool):
    cursor = 0
    while cursor + 4 <= len(extra):
        field_id, field_len = struct.unpack_from("<HH", extra, cursor)
        cursor += 4
        if cursor + field_len > len(extra):
            raise SelectiveExtractionError("Malformed local ZIP extra field")
        data = extra[cursor:cursor + field_len]
        cursor += field_len
        if field_id != 0x0001:
            continue
        pos = 0
        values = []
        for needed in (need_uncompressed, need_compressed):
            if needed:
                if pos + 8 > len(data):
                    raise SelectiveExtractionError("Truncated local ZIP64 size extra field")
                values.append(int.from_bytes(data[pos:pos + 8], "little"))
                pos += 8
            else:
                values.append(None)
        return tuple(values)
    if need_uncompressed or need_compressed:
        raise SelectiveExtractionError("Local ZIP64 size field is missing")
    return None, None


def extract_member(read_at, member: dict[str, Any], expected_name: str, output_path: Path) -> dict[str, Any]:
    """Extract one raw-DEFLATE member and verify its central-directory integrity data."""
    compressed_size = int(member["compressed_size"])
    uncompressed_size = int(member["uncompressed_size"])
    local_offset = int(member["local_header_offset"])
    expected_crc = int(member["crc32"], 16)
    if member.get("disk_start") != 0:
        raise SelectiveExtractionError(f"{expected_name}: member belongs to an unsupported split disk")
    if member.get("encrypted"):
        raise SelectiveExtractionError(f"{expected_name}: encrypted ZIP member is not supported")
    if int(member["compression_method"]) != 8:
        raise SelectiveExtractionError(f"{expected_name}: expected DEFLATE compression method 8")
    if compressed_size <= 0 or compressed_size > MAX_COMPRESSED_MEMBER_BYTES:
        raise SelectiveExtractionError(f"{expected_name}: compressed size exceeds safety limit")
    if uncompressed_size <= 0 or uncompressed_size > MAX_UNCOMPRESSED_MEMBER_BYTES:
        raise SelectiveExtractionError(f"{expected_name}: uncompressed size exceeds safety limit")
    if local_offset < 0:
        raise SelectiveExtractionError(f"{expected_name}: invalid local header offset")

    header = read_at(local_offset, 30)
    fields = struct.unpack("<4s5H3I2H", header)
    (signature, _version, flags, method, _mtime, _mdate, local_crc,
     local_comp32, local_uncomp32, name_len, extra_len) = fields
    if signature != LOCAL_HEADER_SIG:
        raise SelectiveExtractionError(f"{expected_name}: invalid local file header signature")
    if flags & 0x0001 or flags & 0x0040:
        raise SelectiveExtractionError(f"{expected_name}: encrypted ZIP flags are unsupported")
    if flags != int(member.get("flags", flags)):
        raise SelectiveExtractionError(f"{expected_name}: local and central flags disagree")
    if method != 8:
        raise SelectiveExtractionError(f"{expected_name}: local header is not DEFLATE")
    variable = read_at(local_offset + 30, name_len + extra_len)
    raw_name = variable[:name_len]
    encoding = "utf-8" if flags & 0x0800 else "cp437"
    try:
        local_name = raw_name.decode(encoding)
    except UnicodeDecodeError as exc:
        raise SelectiveExtractionError(f"{expected_name}: invalid local filename encoding") from exc
    if local_name != expected_name:
        raise SelectiveExtractionError(
            f"{expected_name}: local filename mismatch ({local_name!r})"
        )
    extra = variable[name_len:]
    local_uncomp64, local_comp64 = _local_zip64_sizes(
        extra, local_uncomp32 == 0xFFFFFFFF, local_comp32 == 0xFFFFFFFF
    )
    if not (flags & 0x0008):  # without a data descriptor, local sizes/CRC must agree
        if local_crc != expected_crc:
            raise SelectiveExtractionError(f"{expected_name}: local CRC32 disagrees with central directory")
        local_comp = local_comp64 if local_comp64 is not None else local_comp32
        local_uncomp = local_uncomp64 if local_uncomp64 is not None else local_uncomp32
        if local_comp != compressed_size or local_uncomp != uncompressed_size:
            raise SelectiveExtractionError(f"{expected_name}: local sizes disagree with central directory")
    else:
        # A data descriptor may leave local CRC/sizes zero; any populated values must agree.
        if local_crc not in (0, expected_crc):
            raise SelectiveExtractionError(f"{expected_name}: descriptor-mode local CRC mismatch")
        local_comp = local_comp64 if local_comp64 is not None else local_comp32
        local_uncomp = local_uncomp64 if local_uncomp64 is not None else local_uncomp32
        if local_comp not in (0, 0xFFFFFFFF, compressed_size):
            raise SelectiveExtractionError(f"{expected_name}: descriptor-mode local compressed size mismatch")
        if local_uncomp not in (0, 0xFFFFFFFF, uncompressed_size):
            raise SelectiveExtractionError(f"{expected_name}: descriptor-mode local uncompressed size mismatch")

    data_offset = local_offset + 30 + name_len + extra_len
    if data_offset < local_offset or data_offset + compressed_size > int(member["central_directory_offset"]):
        raise SelectiveExtractionError(f"{expected_name}: compressed data overlaps central directory")

    decompressor = zlib.decompressobj(-15)
    crc = 0
    written = 0
    remaining = compressed_size
    cursor = data_offset
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("wb") as output:
            while remaining:
                take = min(remaining, MAX_RANGE_BYTES)
                compressed = read_at(cursor, take)
                if len(compressed) != take:
                    raise SelectiveExtractionError(f"{expected_name}: short compressed range read")
                cursor += take
                remaining -= take
                pending = compressed
                while pending:
                    chunk = decompressor.decompress(pending, MAX_DECOMPRESSED_CHUNK)
                    pending = decompressor.unconsumed_tail
                    if chunk:
                        written += len(chunk)
                        if written > uncompressed_size or written > MAX_UNCOMPRESSED_MEMBER_BYTES:
                            raise SelectiveExtractionError(f"{expected_name}: decompressed output exceeded declared limit")
                        crc = zlib.crc32(chunk, crc)
                        output.write(chunk)
                    if not pending:
                        break
            # Drain any output buffered internally by zlib, still under the strict size cap.
            while True:
                chunk = decompressor.decompress(b"", MAX_DECOMPRESSED_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > uncompressed_size or written > MAX_UNCOMPRESSED_MEMBER_BYTES:
                    raise SelectiveExtractionError(f"{expected_name}: decompressed output exceeded declared limit")
                crc = zlib.crc32(chunk, crc)
                output.write(chunk)
            tail = decompressor.flush()
            if tail:
                written += len(tail)
                if written > uncompressed_size or written > MAX_UNCOMPRESSED_MEMBER_BYTES:
                    raise SelectiveExtractionError(f"{expected_name}: flush exceeded declared output limit")
                crc = zlib.crc32(tail, crc)
                output.write(tail)
            if not decompressor.eof or decompressor.unused_data:
                raise SelectiveExtractionError(f"{expected_name}: incomplete DEFLATE stream or trailing compressed bytes")
            if written != uncompressed_size:
                raise SelectiveExtractionError(
                    f"{expected_name}: uncompressed size mismatch ({written} != {uncompressed_size})"
                )
            if (crc & 0xFFFFFFFF) != expected_crc:
                raise SelectiveExtractionError(
                    f"{expected_name}: CRC32 mismatch ({crc & 0xFFFFFFFF:08x} != {expected_crc:08x})"
                )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    return {
        "filename": expected_name,
        "compressed_bytes": compressed_size,
        "uncompressed_bytes": written,
        "crc32": f"{crc & 0xFFFFFFFF:08x}",
        "status": "crc_and_size_verified",
    }


def _connect_archive():
    metadata = [probe_part(name) for name in PART_NAMES]
    failed = [
        item for item in metadata
        if not item["head_ok"] or not item["range_supported"] or not item["range_total"]
    ]
    if failed:
        raise SelectiveExtractionError(
            "Official Kraken part HEAD/Range validation failed: " + json.dumps(failed, sort_keys=True)
        )
    parts = [Part(name, int(item["range_total"])) for name, item in zip(PART_NAMES, metadata)]

    def fetch_part_range(index: int, start: int, end: int) -> bytes:
        part = parts[index]
        url = "https://assets.kraken.com/marketing/institutions/" + part.name
        expected = end - start + 1
        if expected <= 0 or expected > MAX_RANGE_BYTES:
            raise SelectiveExtractionError("Requested byte range exceeds 1 MiB safety cap")
        response = _request(url, "GET", {"Range": f"bytes={start}-{end}"})
        try:
            expected_header = f"bytes {start}-{end}/{part.size}"
            actual_header = response.headers.get("Content-Range", "").strip()
            if response.status != 206 or actual_header != expected_header:
                raise SelectiveExtractionError(
                    f"{part.name}: expected HTTP 206 {expected_header}, got "
                    f"HTTP {response.status} {actual_header!r}"
                )
            body = response.read(expected + 1)
            if len(body) != expected:
                raise SelectiveExtractionError(
                    f"{part.name}: expected {expected} bytes, received {len(body)}"
                )
            return body
        finally:
            response.close()

    return RangeArchive(parts, fetch_part_range)


def run_live_validation() -> dict[str, Any]:
    archive = _connect_archive()
    report = inspect_with_reader(archive.read_at, archive.total_size)
    metadata_bytes_read = archive.bytes_read
    metadata_range_requests = archive.requests
    if not report["all_six_unique"]:
        raise SelectiveExtractionError(
            "The six target names are not all unique: " + json.dumps({
                "missing": report["missing_targets"],
                "ambiguous": report["ambiguous_targets"],
            })
        )
    report["zip64"]["central_directory_offset"] = int(report["zip64"]["central_directory_offset"])
    central_offset = int(report["zip64"]["central_directory_offset"])
    validated = []
    segment_reports = []
    backtest_reports = []
    out_of_sample_reports = []
    out_of_sample_5of5_reports = []
    walk_forward_5of5_reports = []
    with tempfile.TemporaryDirectory(prefix="kraken-selective-") as temp_dir:
        root = Path(temp_dir)
        extracted_paths = {}
        for filename, (symbol, timeframe) in EXPECTED_MEMBERS.items():
            entries = report["target_matches"][filename]
            if len(entries) != 1:
                raise SelectiveExtractionError(f"{filename}: expected exactly one central-directory entry")
            member = dict(entries[0])
            member["central_directory_offset"] = central_offset
            # Require the archive to use the expected exact root-level basename.
            if member["name"] != filename:
                raise SelectiveExtractionError(
                    f"{filename}: unexpected archive path {member['name']!r}"
                )
            extracted = root / filename
            extraction = extract_member(archive.read_at, member, filename, extracted)
            extracted_paths[filename] = extracted
            loaded = load_kraken_ohlcvt_csv(
                extracted, timeframe, require_contiguous=False
            )
            meta = loaded["metadata"]
            validated.append({
                "filename": filename,
                "symbol": symbol,
                "timeframe_minutes": timeframe,
                "rows": meta["row_count"],
                "first_timestamp_ms": meta["first_timestamp_ms"],
                "last_timestamp_ms": meta["last_timestamp_ms"],
                "missing_intervals": meta["missing_intervals"],
                "first_gap": meta["first_gap"],
                "csv_sha256": meta["source_sha256"],
                "extraction": extraction,
                "status": "ohlcvt_validated",
            })
            del loaded

        # Process one market at a time to bound memory; all files stay temporary.
        from datetime import datetime, timezone
        for market, base_name in (("BTC/USDT", "XBTUSDT"), ("ETH/USDT", "ETHUSDT"), ("SOL/USDT", "SOLUSDT")):
            five = load_kraken_ohlcvt_csv(extracted_paths[f"{base_name}_5.csv"], 5, require_contiguous=False)
            fifteen = load_kraken_ohlcvt_csv(extracted_paths[f"{base_name}_15.csv"], 15, require_contiguous=False)
            paired = build_aligned_contiguous_segments(five["candles"], fifteen["candles"], min_5m_candles=200, min_15m_candles=200)
            segment_rows = []
            for segment in paired["segments"]:
                meta = segment["metadata"]
                segment_rows.append({
                    **meta,
                    "first_5m_utc": datetime.fromtimestamp(meta["first_5m_timestamp"] / 1000, tz=timezone.utc).isoformat(),
                    "last_5m_utc": datetime.fromtimestamp(meta["last_5m_timestamp"] / 1000, tz=timezone.utc).isoformat(),
                })
            segment_reports.append({"symbol": market, "metadata": paired["metadata"], "segments": segment_rows})
            backtest = backtest_segments(paired["segments"], initial_balance=100.0)
            backtest_reports.append({
                "symbol": market,
                **{key: value for key, value in backtest.items()
                   if key not in ("segments", "trades")},
                "segment_results": backtest["segments"],
            })
            oos = backtest_out_of_sample(paired["segments"], initial_balance=100.0, train_fraction=0.70, minimum_conditions=4)
            out_of_sample_reports.append({
                "symbol": market,
                **oos,
            })
            oos_5of5 = backtest_out_of_sample(paired["segments"], initial_balance=100.0, train_fraction=0.70, minimum_conditions=5)
            out_of_sample_5of5_reports.append({
                "symbol": market,
                **oos_5of5,
            })
            walk_forward_5of5 = backtest_5of5_walk_forward(
                paired["segments"], initial_balance=100.0
            )
            walk_forward_5of5_reports.append({
                "symbol": market,
                **walk_forward_5of5,
            })
            del backtest, oos, oos_5of5, paired, five, fifteen
    return {        "status": "all_six_csvs_extracted_and_validated",
        "archive_size_bytes": archive.total_size,
        "metadata_bytes_read": metadata_bytes_read,
        "metadata_range_requests": metadata_range_requests,
        "range_bytes_read_total": archive.bytes_read,
        "range_requests_total": archive.requests,
        "member_payload_bytes_downloaded": sum(
            int(item["compressed_bytes"]) for item in
            [row["extraction"] for row in validated]
        ),
        "members": validated,
        "gap_aware_segments": segment_reports,
        "historical_backtest": backtest_reports,
        "out_of_sample_backtest": out_of_sample_reports,
        "out_of_sample_5of5_counterfactual": out_of_sample_5of5_reports,
        "walk_forward_5of5_disjoint_folds": walk_forward_5of5_reports,
        "gaps_filled": False,
        "note": "CSV payloads were temporary to this CI job; no market data was committed to Git.",
    }


def main() -> int:
    try:
        print(json.dumps(run_live_validation(), indent=2, sort_keys=True))
        return 0
    except (SelectiveExtractionError, ArchiveInspectionError, ValueError,
            OSError, TimeoutError, urllib.error.URLError, zlib.error) as exc:
        print(json.dumps({
            "status": "selective_extraction_failed",
            "error": str(exc),
            "no_archive_reassembly": True,
        }, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
