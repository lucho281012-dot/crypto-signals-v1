"""Inspect Kraken OHLCVT ZIP metadata without extracting market CSV data.

The inspector reads the ZIP central directory and, when present, a bounded
MANIFEST.json. It never extracts files or assumes an undocumented manifest
schema. Candidate CSVs are matched by exact native market ID and timeframe.
"""
import json
import re
import zipfile
from pathlib import PurePosixPath

DEFAULT_MARKETS = ("XBTUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_TIMEFRAMES = (5, 15)
MAX_MANIFEST_BYTES = 5 * 1024 * 1024


def inspect_kraken_archive(
    archive_path,
    market_ids=DEFAULT_MARKETS,
    timeframes=DEFAULT_TIMEFRAMES,
):
    """Return a deterministic inventory of exact market/timeframe members.

    A candidate is identified only when its basename is exactly
    '<native_market_id>_<minutes>.csv'. Nested archive paths are preserved.
    Missing or ambiguous matches are reported, never guessed.
    """
    market_ids = tuple(market_ids)
    timeframes = tuple(timeframes)
    if not market_ids or any(
        not isinstance(item, str) or not re.fullmatch(r"[A-Z0-9]+", item)
        for item in market_ids
    ):
        raise ValueError("market_ids debe contener IDs nativos alfanuméricos")
    if not timeframes or any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 0
        for item in timeframes
    ):
        raise ValueError("timeframes debe contener minutos enteros positivos")
    if len(set(market_ids)) != len(market_ids) or len(set(timeframes)) != len(timeframes):
        raise ValueError("No se permiten IDs o timeframes duplicados")

    with zipfile.ZipFile(archive_path, "r") as archive:
        members = archive.infolist()
        files = [item for item in members if not item.is_dir()]
        manifest_members = [
            item for item in files
            if PurePosixPath(item.filename).name.lower() == "manifest.json"
        ]
        manifest = {
            "status": "absent",
            "paths": [item.filename for item in manifest_members],
        }
        if len(manifest_members) > 1:
            manifest["status"] = "ambiguous"
        elif len(manifest_members) == 1:
            item = manifest_members[0]
            if item.file_size > MAX_MANIFEST_BYTES:
                manifest["status"] = "too_large"
                manifest["size_bytes"] = item.file_size
            else:
                try:
                    parsed = json.loads(archive.read(item).decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
                    manifest["status"] = "invalid"
                    manifest["error"] = type(exc).__name__
                else:
                    manifest["status"] = "parsed"
                    manifest["json_type"] = (
                        "object" if isinstance(parsed, dict)
                        else "array" if isinstance(parsed, list)
                        else type(parsed).__name__
                    )
                    manifest["top_level_keys"] = (
                        sorted(str(key) for key in parsed.keys())
                        if isinstance(parsed, dict) else []
                    )
                    manifest["schema_interpreted"] = False

        csv_members = [
            item for item in files
            if PurePosixPath(item.filename).suffix.lower() == ".csv"
        ]
        results = []
        for market_id in market_ids:
            for minutes in timeframes:
                expected = f"{market_id}_{minutes}.csv"
                matches = sorted(
                    item.filename for item in csv_members
                    if PurePosixPath(item.filename).name == expected
                )
                results.append({
                    "market_id": market_id,
                    "timeframe_minutes": minutes,
                    "expected_basename": expected,
                    "status": (
                        "unique" if len(matches) == 1
                        else "missing" if not matches
                        else "ambiguous"
                    ),
                    "matches": matches,
                    "candidate_count": len(matches),
                })

        return {
            "archive": str(archive_path),
            "archive_member_count": len(files),
            "csv_member_count": len(csv_members),
            "manifest": manifest,
            "matches": results,
            "csv_data_extracted": False,
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Inventario seguro de miembros de un ZIP OHLCVT de Kraken"
    )
    parser.add_argument("archive", help="Ruta al archivo ZIP de Kraken")
    parser.add_argument(
        "--markets", nargs="+", default=list(DEFAULT_MARKETS),
        help="IDs nativos exactos (por defecto: XBTUSDT ETHUSDT SOLUSDT)",
    )
    parser.add_argument(
        "--timeframes", nargs="+", type=int, default=list(DEFAULT_TIMEFRAMES),
        help="Timeframes en minutos (por defecto: 5 15)",
    )
    args = parser.parse_args()
    report = inspect_kraken_archive(args.archive, args.markets, args.timeframes)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
