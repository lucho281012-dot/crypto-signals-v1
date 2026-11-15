# Kraken selective CSV extraction and validation

## Purpose

Fetch only the six previously located Kraken OHLCVT CSV members using HTTP byte ranges. The workflow does not download or assemble the 9.55 GB archive.

## Selected members

- `XBTUSDT_5.csv` and `XBTUSDT_15.csv` (BTC/USDT)
- `ETHUSDT_5.csv` and `ETHUSDT_15.csv` (ETH/USDT)
- `SOLUSDT_5.csv` and `SOLUSDT_15.csv` (SOL/USDT)

## Extraction controls

- Revalidates all five official archive part sizes and HTTP 206/Content-Range behavior before extraction.
- Re-reads ZIP64 central-directory metadata and requires exactly one occurrence of each exact root-level member name.
- Validates local file header signature, filename, flags, compression method, CRC/sizes when present, and data bounds against the central directory.
- Supports only unencrypted DEFLATE members on disk 0; unsupported/encrypted members fail closed.
- Fetches compressed member bytes in HTTP ranges of at most 1 MiB, including ranges that cross a split-part boundary.
- Caps each compressed member at 64 MiB and each decompressed member at 50 MiB.
- Uses raw-DEFLATE streaming with bounded output chunks and checks final uncompressed size, stream EOF, absence of trailing compressed bytes, and CRC32.
- Passes each temporary CSV to the strict Kraken OHLCVT importer using `require_contiguous=False` so real no-trade intervals are reported, never filled.
- Reports row counts, UTC coverage, gaps, and CSV SHA-256 hashes, with ZIP metadata bytes counted separately from compressed member payload bytes.
- Extracted CSVs exist only in the ephemeral GitHub Actions runner temp directory; no market-data files are committed to Git.

## Run

```bash
python -m unittest -v test_kraken_selective_csv_extractor.py
python kraken_selective_csv_extractor.py
```

The live workflow runs on pushes to the isolated `paper-kraken-selective-csv-extractor` branch. Pull-request validation runs offline tests only.

## Important interpretation

A successful run confirms the selected CSV members were range-fetched, decompressed, CRC/size verified, and structurally validated as Kraken OHLCVT rows. It does not yet establish that the data are contiguous enough for the current strategy adapter. Gaps are reported, not filled; any downstream backtest must explicitly handle contiguous segments and align 5m/15m candles without look-ahead.

No signal rules, active simulator state, paper balance, or exchange credentials are changed. This workflow performs no trading.

## Data retention

The workflow prints provenance metadata and SHA-256 values. The extracted market data are intentionally not stored in the repository or as a long-lived artifact. A later backtest workflow can repeat the bounded selective extraction, or a separately reviewed artifact-retention step can be added if needed.