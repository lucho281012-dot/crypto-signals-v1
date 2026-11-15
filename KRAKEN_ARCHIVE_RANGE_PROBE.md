# Kraken OHLCVT archive range probe

This utility checks whether all five official Kraken archive parts support HTTP byte-range requests before any large transfer is attempted.

## Safety properties
- Uses only the five hard-coded official Kraken part names.
- Sends a HEAD request and a GET request with Range: bytes=0-0.
- Accepts range support only for HTTP 206 with exact Content-Range: bytes 0-0/<total>.
- Never reads or saves the response body. If a server ignores Range and responds with HTTP 200, the response is closed immediately.
- Reports zero archive bytes downloaded by the utility.
- Does not assemble, extract, or modify archive or repository data.

## Run
    python -m unittest -v test_kraken_archive_range_probe.py
    python kraken_archive_range_probe.py

The live command requires network access to Kraken. A network failure is a probe error, not evidence that the archive is unavailable.

## GitHub Actions
The workflow runs mocked unit tests on push and pull request. The live network probe is manual (workflow_dispatch) so ordinary CI does not depend on Kraken availability. In Actions, select Kraken Archive Range Probe and choose Run workflow for the metadata-only check.

## Interpretation and limits
If all five parts return valid byte ranges and known totals, range retrieval may be technically feasible. This does not prove that the ZIP central directory can be fetched and interpreted safely or that selected CSV members can be extracted remotely. A follow-up must validate ZIP64/end-of-central-directory metadata and member byte ranges before reading member data.

If any part ignores Range, returns malformed metadata, or cannot be reached, do not attempt selective retrieval through this method. No full archive download is performed by this probe.
