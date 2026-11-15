# Kraken historical OHLCVT import and validation

## Official source and format
Kraken publishes downloadable OHLCVT CSV archives for its markets. Each pair's
file contains headerless rows with seven columns:
timestamp, open, high, low, close, volume, trades.
Timestamps are Unix seconds. The archive includes 5-minute and 15-minute files
and a MANIFEST.json. Kraken documents that intervals without trades are omitted,
not zero-filled.

Official documentation:
https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data

## Importer behavior
- Converts Unix seconds to milliseconds (CCXT-compatible timestamps).
- Validates column count, finite numeric values, OHLC consistency, timestamp
  alignment, ordering, duplicates, and interval spacing.
- Computes SHA-256 of the exact source CSV and records basic provenance.
- Rejects gaps by default. Diagnostic mode reports gaps without filling them.
- Never edits, downloads, or writes into the active simulator state.

## Important caveat
A missing Kraken candle means no trades occurred in that interval. The importer
does not invent a zero-volume candle. The signal adapter requires contiguous
series, so datasets with gaps must be excluded or separately assessed before
strategy evaluation; do not silently forward-fill or zero-fill them.

## Not included
No market data is committed to this repository. No strategy performance result
is produced by this importer. The exact selected pair, archive version,
MANIFEST, CSV SHA-256, date coverage, and gap report must be recorded before
running a historical backtest.
