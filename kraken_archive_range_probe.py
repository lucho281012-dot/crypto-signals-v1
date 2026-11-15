"""Probe Kraken archive HTTP range support without downloading archive parts."""
from __future__ import annotations
import json, re, sys, urllib.error, urllib.request
from typing import Any

PART_NAMES = tuple(f"Kraken_OHLCVT_Full.zip.part{i:02d}" for i in range(5))
BASE_URL = "https://assets.kraken.com/marketing/institutions/"
TIMEOUT_SECONDS = 20

def _request(url: str, method: str, headers: dict[str, str] | None = None):
    request_headers = {"User-Agent": "Mozilla/5.0 (compatible; KrakenArchiveRangeProbe/1.0)"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, method=method, headers=request_headers)
    return urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)

def probe_part(part_name: str) -> dict[str, Any]:
    """Inspect HEAD metadata and test a one-byte range request; never save data."""
    if part_name not in PART_NAMES:
        raise ValueError(f"Unsupported archive part: {part_name}")
    url = BASE_URL + part_name
    result = {"part": part_name, "url": url, "head_ok": False,
              "content_length": None, "accept_ranges": None,
              "range_supported": False, "range_total": None,
              "range_status": None, "error": None}
    try:
        try:
            with _request(url, "HEAD") as response:
                result["head_ok"] = 200 <= response.status < 400
                raw_length = response.headers.get("Content-Length")
                result["content_length"] = int(raw_length) if raw_length and raw_length.isdigit() else None
                result["accept_ranges"] = response.headers.get("Accept-Ranges")
        except urllib.error.HTTPError as exc:
            result["error"] = f"HEAD HTTP {exc.code}"
        try:
            response = _request(url, "GET", {"Range": "bytes=0-0"})
            try:
                result["range_status"] = response.status
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes 0-0/(\d+)", content_range.strip())
                if response.status == 206 and match:
                    result["range_supported"] = True
                    result["range_total"] = int(match.group(1))
                elif response.status == 200:
                    result["error"] = "Server ignored Range; response body was not read"
                else:
                    result["error"] = f"Unexpected range response: HTTP {response.status}"
            finally:
                response.close()
        except urllib.error.HTTPError as exc:
            result["range_status"] = exc.code
            result["error"] = f"Range HTTP {exc.code}"
        except (OSError, TimeoutError) as exc:
            result["error"] = f"Range request failed: {type(exc).__name__}: {exc}"
    except (OSError, TimeoutError) as exc:
        result["error"] = f"Request failed: {type(exc).__name__}: {exc}"
    return result

def probe_all() -> dict[str, Any]:
    parts = [probe_part(name) for name in PART_NAMES]
    return {"source": "Kraken official OHLCVT full archive",
            "downloaded_archive_bytes": 0, "parts": parts,
            "all_ranges_supported": all(x["range_supported"] for x in parts),
            "safe_for_selective_range_retrieval": all(
                x["range_supported"] and x["range_total"] for x in parts)}

def main() -> int:
    report = probe_all()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_ranges_supported"] else 1

if __name__ == "__main__":
    sys.exit(main())
