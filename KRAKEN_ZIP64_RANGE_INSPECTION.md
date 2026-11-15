# Kraken ZIP64 remote range inspection

## Purpose

Inspect the official five-part Kraken OHLCVT archive without downloading or reassembling the archive. The inspector reads only:
- the final ZIP tail needed to locate EOCD and ZIP64 EOCD metadata;
- the ZIP64 EOCD fixed record;
- the central-directory metadata, in bounded 1 MiB HTTP byte-range requests.

It searches for these exact basenames:
- `XBTUSDT_5.csv`, `XBTUSDT_15.csv`
- `ETHUSDT_5.csv`, `ETHUSDT_15.csv`
- `SOLUSDT_5.csv`, `SOLUSDT_15.csv`

The names are targets, not assumptions: the report identifies missing and duplicate matches.

## Safety limits

- Uses the five official part names and verifies each part with HEAD plus HTTP 206 byte-range metadata before reading.
- Sends a standard User-Agent, as required by the successful range probe.
- Reads no more than 65,557 bytes for the ZIP tail.
- Reads central-directory metadata only, with a 64 MiB hard cap and 1 MiB maximum per request.
- Requires ZIP64 records and validates offsets, declared record counts, directory boundaries, and central-directory signatures.
- Rejects true multi-disk ZIP layouts; this reader treats the five `.partNN` objects as raw consecutive byte segments of one ZIP64 file.
- Does not request local file headers or member payloads, decompress files, assemble parts, or write archive data to disk.
- Reports member payload bytes downloaded as zero.

The official archive is approximately 9.56 GB across the five parts. The inspector does not fetch that payload.

## Run

```bash
python -m unittest -v test_kraken_zip64_range_inspector.py
python kraken_zip64_range_inspector.py
```

The live command requires outbound network access to the official Kraken asset host. It is run by GitHub Actions on pushes to the isolated `paper-kraken-zip64-range-inspector` branch. Pull-request runs execute only offline unit tests.

## Interpretation

A successful report with `all_six_unique: true` confirms that the six exact member names exist uniquely in the central directory and provides their compressed/uncompressed sizes, compression method, CRC32, and local-header offsets.

This does **not** yet prove that the six CSV payloads can be fetched safely or decoded. A separate implementation must validate each local header against its central-directory record, handle any member whose compressed byte range crosses a split-part boundary, stream decompression with strict output limits, and verify CRC32 and uncompressed size before passing CSV bytes to the Kraken OHLCVT validator.

If the central directory exceeds the configured cap, uses a true multi-disk layout, has unsupported structure, or cannot be fetched with exact HTTP 206 ranges, the inspector fails closed. Do not increase limits or fall back to full archive downloads without a separate review.