"""Inspect Kraken's split ZIP64 archive directory using bounded HTTP byte ranges.

Only the ZIP tail and central-directory metadata are fetched. Member payloads are
never downloaded, decompressed, or written to disk.
"""
from __future__ import annotations

import json
import struct
import sys
import urllib.error
from dataclasses import dataclass
from typing import Callable, Any

from kraken_archive_range_probe import PART_NAMES, probe_part, _request

MAX_TAIL_BYTES = 65_557  # EOCD + maximum ZIP comment
MAX_CENTRAL_DIRECTORY_BYTES = 64 * 1024 * 1024
RANGE_CHUNK_BYTES = 1024 * 1024
TARGETS = {
    "XBTUSDT_5.csv", "XBTUSDT_15.csv",
    "ETHUSDT_5.csv", "ETHUSDT_15.csv",
    "SOLUSDT_5.csv", "SOLUSDT_15.csv",
}
EOCD_SIG = b"PK\x05\x06"
ZIP64_EOCD_SIG = b"PK\x06\x06"
ZIP64_LOCATOR_SIG = b"PK\x06\x07"
CENTRAL_SIG = b"PK\x01\x02"
CENTRAL_DIGITAL_SIG = b"PK\x05\x05"


class ArchiveInspectionError(RuntimeError):
    """Raised when archive metadata is unsupported, inconsistent, or unsafe."""


@dataclass(frozen=True)
class Part:
    name: str
    size: int


class RangeArchive:
    """Virtual concatenated view over the five raw split-volume files."""

    def __init__(self, parts: list[Part], fetch_part_range: Callable[[int, int, int], bytes]):
        if len(parts) != len(PART_NAMES):
            raise ArchiveInspectionError(f"Expected {len(PART_NAMES)} parts, got {len(parts)}")
        if any(p.name != PART_NAMES[i] or p.size <= 0 for i, p in enumerate(parts)):
            raise ArchiveInspectionError("Part names/order/sizes do not match the official archive")
        self.parts = parts
        self.fetch_part_range = fetch_part_range
        self.starts: list[int] = []
        total = 0
        for part in parts:
            self.starts.append(total)
            total += part.size
        self.total_size = total
        self.bytes_read = 0
        self.requests = 0

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self.total_size:
            raise ArchiveInspectionError("Requested range is outside the concatenated archive")
        if length > RANGE_CHUNK_BYTES:
            raise ArchiveInspectionError("Internal range read exceeds the 1 MiB safety limit")
        if length == 0:
            return b""
        out = bytearray()
        cursor = offset
        remaining = length
        for index, part in enumerate(self.parts):
            part_start = self.starts[index]
            part_end = part_start + part.size
            if cursor >= part_end or cursor < part_start:
                continue
            local_start = cursor - part_start
            take = min(remaining, part.size - local_start)
            chunk = self.fetch_part_range(index, local_start, local_start + take - 1)
            if len(chunk) != take:
                raise ArchiveInspectionError(
                    f"Short range response for {part.name}: expected {take}, got {len(chunk)}"
                )
            out.extend(chunk)
            self.bytes_read += len(chunk)
            self.requests += 1
            cursor += take
            remaining -= take
            if remaining == 0:
                break
        if remaining:
            raise ArchiveInspectionError("Could not satisfy virtual range across archive parts")
        return bytes(out)

    def read_bounded(self, offset: int, length: int) -> bytes:
        if length < 0 or length > MAX_CENTRAL_DIRECTORY_BYTES:
            raise ArchiveInspectionError(
                f"Central directory size {length} exceeds {MAX_CENTRAL_DIRECTORY_BYTES}-byte limit"
            )
        out = bytearray()
        cursor = offset
        remaining = length
        while remaining:
            take = min(remaining, RANGE_CHUNK_BYTES)
            out.extend(self.read_at(cursor, take))
            cursor += take
            remaining -= take
        return bytes(out)


def _find_eocd(tail: bytes) -> tuple[int, int]:
    """Return (EOCD position in tail, ZIP comment length), validating its boundary."""
    pos = tail.rfind(EOCD_SIG)
    while pos >= 0:
        if pos + 22 <= len(tail):
            comment_len = struct.unpack_from("<H", tail, pos + 20)[0]
            if pos + 22 + comment_len == len(tail):
                return pos, comment_len
        pos = tail.rfind(EOCD_SIG, 0, pos)
    raise ArchiveInspectionError("End of central directory record not found in bounded archive tail")


def _parse_zip64_directory(read_at: Callable[[int, int], bytes], total_size: int) -> dict[str, int]:
    tail_len = min(MAX_TAIL_BYTES, total_size)
    tail_offset = total_size - tail_len
    tail = read_at(tail_offset, tail_len)
    eocd_pos, _ = _find_eocd(tail)
    eocd_global = tail_offset + eocd_pos
    if eocd_pos < 20:
        raise ArchiveInspectionError("ZIP64 locator is not immediately before EOCD")
    locator = tail[eocd_pos - 20:eocd_pos]
    sig, zip64_disk, zip64_offset, disk_count = struct.unpack("<4sIQI", locator)
    if sig != ZIP64_LOCATOR_SIG:
        raise ArchiveInspectionError("ZIP64 locator missing; only ZIP64 archives are supported")
    if zip64_disk != 0 or disk_count != 1:
        raise ArchiveInspectionError(
            f"Unsupported true multi-disk ZIP layout (locator disk={zip64_disk}, disks={disk_count})"
        )
    if zip64_offset + 56 > eocd_global:
        raise ArchiveInspectionError("ZIP64 EOCD offset is outside the valid pre-EOCD region")
    fixed = read_at(zip64_offset, 56)
    fields = struct.unpack("<4sQ2H2I4Q", fixed)
    (zsig, record_size, _made, _needed, this_disk, cd_disk,
     entries_disk, entries_total, cd_size, cd_offset) = fields
    if zsig != ZIP64_EOCD_SIG or record_size < 44:
        raise ArchiveInspectionError("Invalid ZIP64 EOCD signature or record size")
    if this_disk != 0 or cd_disk != 0 or entries_disk != entries_total:
        raise ArchiveInspectionError("Archive uses unsupported multi-disk ZIP64 directory layout")
    if zip64_offset + 12 + record_size > eocd_global:
        raise ArchiveInspectionError("ZIP64 EOCD record extends beyond the EOCD boundary")
    if cd_size > MAX_CENTRAL_DIRECTORY_BYTES:
        raise ArchiveInspectionError(
            f"Central directory is {cd_size} bytes; safety cap is {MAX_CENTRAL_DIRECTORY_BYTES}"
        )
    if cd_offset + cd_size > zip64_offset:
        raise ArchiveInspectionError("Central directory overlaps ZIP64 end records")
    if cd_offset < 0 or cd_offset + cd_size > total_size:
        raise ArchiveInspectionError("Central directory range is outside the archive")
    return {
        "zip64_eocd_offset": zip64_offset,
        "eocd_offset": eocd_global,
        "central_directory_offset": cd_offset,
        "central_directory_size": cd_size,
        "entries_total": entries_total,
        "disk_count": disk_count,
    }


def _zip64_values(extra: bytes, need_uncompressed: bool, need_compressed: bool,
                  need_offset: bool, need_disk: bool) -> tuple[int | None, int | None, int | None, int | None]:
    cursor = 0
    while cursor + 4 <= len(extra):
        field_id, field_len = struct.unpack_from("<HH", extra, cursor)
        cursor += 4
        if cursor + field_len > len(extra):
            raise ArchiveInspectionError("Malformed central-directory extra field")
        data = extra[cursor:cursor + field_len]
        cursor += field_len
        if field_id != 0x0001:
            continue
        p = 0
        values: list[int | None] = [None, None, None, None]
        for index, needed in enumerate((need_uncompressed, need_compressed, need_offset, need_disk)):
            if not needed:
                continue
            width = 4 if index == 3 else 8
            if p + width > len(data):
                raise ArchiveInspectionError("Truncated ZIP64 extended information extra field")
            values[index] = int.from_bytes(data[p:p + width], "little")
            p += width
        return tuple(values)  # type: ignore[return-value]
    if any((need_uncompressed, need_compressed, need_offset, need_disk)):
        raise ArchiveInspectionError("Required ZIP64 extended information field is missing")
    return None, None, None, None


def _parse_central_directory(data: bytes, expected_entries: int) -> dict[str, list[dict[str, Any]]]:
    matches: dict[str, list[dict[str, Any]]] = {name: [] for name in sorted(TARGETS)}
    cursor = 0
    entries_seen = 0
    while cursor < len(data):
        if data[cursor:cursor + 4] == CENTRAL_DIGITAL_SIG:
            if cursor + 6 > len(data):
                raise ArchiveInspectionError("Truncated central-directory digital signature")
            sig_len = struct.unpack_from("<H", data, cursor + 4)[0]
            cursor += 6 + sig_len
            if cursor != len(data):
                raise ArchiveInspectionError("Unexpected bytes after central-directory digital signature")
            break
        if cursor + 46 > len(data):
            raise ArchiveInspectionError("Truncated central-directory file header")
        fields = struct.unpack_from("<4s6H3I5H2I", data, cursor)
        (sig, _made, _needed, flags, method, _mtime, _mdate, crc,
         comp32, uncomp32, name_len, extra_len, comment_len, disk_start16,
         _int_attr, _ext_attr, local_offset32) = fields
        if sig != CENTRAL_SIG:
            raise ArchiveInspectionError(f"Invalid central-directory signature at byte {cursor}")
        end = cursor + 46 + name_len + extra_len + comment_len
        if end > len(data):
            raise ArchiveInspectionError("Central-directory entry exceeds declared directory size")
        raw_name = data[cursor + 46:cursor + 46 + name_len]
        extra_start = cursor + 46 + name_len
        extra = data[extra_start:extra_start + extra_len]
        encoding = "utf-8" if flags & 0x0800 else "cp437"
        try:
            name = raw_name.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ArchiveInspectionError(f"Cannot decode central-directory filename: {exc}") from exc
        uncomp, comp, local_offset, disk_start = _zip64_values(
            extra,
            uncomp32 == 0xFFFFFFFF,
            comp32 == 0xFFFFFFFF,
            local_offset32 == 0xFFFFFFFF,
            disk_start16 == 0xFFFF,
        )
        if uncomp is None:
            uncomp = uncomp32
        if comp is None:
            comp = comp32
        if local_offset is None:
            local_offset = local_offset32
        if disk_start is None:
            disk_start = disk_start16
        basename = name.replace("\\", "/").rsplit("/", 1)[-1]
        if basename in matches:
            matches[basename].append({
                "name": name,
                "compressed_size": comp,
                "uncompressed_size": uncomp,
                "compression_method": method,
                "crc32": f"{crc:08x}",
                "local_header_offset": local_offset,
                "disk_start": disk_start,
                "encrypted": bool(flags & 0x0001),
                "flags": flags,
            })
        entries_seen += 1
        cursor = end
    if cursor != len(data):
        raise ArchiveInspectionError("Central-directory parser did not consume declared directory bytes")
    if entries_seen != expected_entries:
        raise ArchiveInspectionError(
            f"ZIP64 declares {expected_entries} entries but parsed {entries_seen}"
        )
    return matches


def inspect_with_reader(read_at: Callable[[int, int], bytes], total_size: int,
                        bytes_read: int = 0, requests: int = 0) -> dict[str, Any]:
    directory = _parse_zip64_directory(read_at, total_size)
    cd_data = bytearray()
    cursor = directory["central_directory_offset"]
    remaining = directory["central_directory_size"]
    while remaining:
        take = min(remaining, RANGE_CHUNK_BYTES)
        cd_data.extend(read_at(cursor, take))
        cursor += take
        remaining -= take
    matches = _parse_central_directory(bytes(cd_data), directory["entries_total"])
    found = {name: entries for name, entries in matches.items() if entries}
    missing = sorted(name for name, entries in matches.items() if not entries)
    ambiguous = sorted(name for name, entries in matches.items() if len(entries) > 1)
    return {
        "archive_size_bytes": total_size,
        "zip64": directory,
        "target_matches": found,
        "missing_targets": missing,
        "ambiguous_targets": ambiguous,
        "all_six_unique": len(found) == 6 and not missing and not ambiguous,
        "member_payload_bytes_downloaded": 0,
        "metadata_bytes_read": bytes_read,
        "range_requests": requests,
    }


def inspect_live() -> dict[str, Any]:
    metadata = [probe_part(name) for name in PART_NAMES]
    failed = [x for x in metadata if not x["head_ok"] or not x["range_supported"] or not x["range_total"]]
    if failed:
        raise ArchiveInspectionError(
            "Cannot inspect ZIP64 because one or more parts failed HEAD/Range validation: "
            + json.dumps(failed, sort_keys=True)
        )
    parts = [Part(name, int(meta["range_total"])) for name, meta in zip(PART_NAMES, metadata)]

    def fetch_part_range(index: int, start: int, end: int) -> bytes:
        part = parts[index]
        url = "https://assets.kraken.com/marketing/institutions/" + part.name
        expected = end - start + 1
        response = _request(url, "GET", {"Range": f"bytes={start}-{end}"})
        try:
            content_range = response.headers.get("Content-Range", "")
            expected_range = f"bytes {start}-{end}/{part.size}"
            if response.status != 206 or content_range.strip() != expected_range:
                raise ArchiveInspectionError(
                    f"{part.name}: expected HTTP 206 {expected_range}, got "
                    f"HTTP {response.status} {content_range!r}"
                )
            body = response.read(expected + 1)
            if len(body) != expected:
                raise ArchiveInspectionError(
                    f"{part.name}: expected {expected} metadata bytes, received {len(body)}"
                )
            return body
        finally:
            response.close()

    archive = RangeArchive(parts, fetch_part_range)
    result = inspect_with_reader(archive.read_at, archive.total_size)
    result["metadata_bytes_read"] = archive.bytes_read
    result["range_requests"] = archive.requests
    result["parts"] = [{"name": p.name, "size_bytes": p.size} for p in parts]
    result["source"] = "Kraken official OHLCVT full archive"
    return result


def main() -> int:
    try:
        report = inspect_live()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["all_six_unique"] else 2
    except (ArchiveInspectionError, OSError, TimeoutError, urllib.error.URLError) as exc:
        print(json.dumps({"status": "inspection_failed", "error": str(exc),
                          "member_payload_bytes_downloaded": 0}, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
