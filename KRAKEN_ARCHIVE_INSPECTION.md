# Kraken OHLCVT archive inspection

## Purpose

This isolated utility inventories a Kraken ZIP archive before any historical
market data is imported. It uses the ZIP central directory and optionally
parses a small `MANIFEST.json`; it does not extract CSV data, download archives,
or write to the active Paper Trading state.

## Exact matching

The default audit checks these native Kraken market IDs and timeframes:

- `XBTUSDT`: 5m and 15m
- `ETHUSDT`: 5m and 15m
- `SOLUSDT`: 5m and 15m

A CSV is considered a match only if its basename exactly equals
`<native_market_id>_<minutes>.csv`. Directory prefixes are retained. Missing
pairs are not substituted (for example, XBTUSD is not XBTUSDT); duplicate
basenames are reported as ambiguous. The utility deliberately does not infer
the MANIFEST schema: it reports whether JSON was parsed, its top-level type,
and object keys only.

## Usage

```bash
python kraken_archive_inspector.py /path/to/Kraken_OHLCVT_Full.zip
python kraken_archive_inspector.py /path/to/archive.zip --markets XBTUSDT ETHUSDT --timeframes 5 15
python -m unittest -v test_kraken_archive_inspector.py
```

## Safety and limitations

- No extraction of market CSVs and no bulk data copy.
- No network calls, exchange credentials, order placement, or simulator-state
  access.
- The archive is not validated as authentic merely because its ZIP structure
  can be read. Preserve the official archive checksum and verify it separately.
- A unique filename match does not prove that the CSV contents have correct
  market identity, timeframe, coverage, or integrity. The existing strict
  OHLCVT importer must validate each selected CSV and record its SHA-256.
- Kraken omits intervals with no trades. Gaps must not be silently filled;
  the strategy adapter currently requires contiguous candle series.
- No historical backtest or profitability conclusion is produced here.

The exact archive member names and MANIFEST structure remain unverified until
this inspector is run against the actual official archive.
