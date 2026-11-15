# Kraken live gap-aware validation

This workflow repeats the verified selective byte-range extraction of the six
official Kraken OHLCVT CSV members, validates their CRC/size and OHLCVT schema,
then pairs 5m candles with the latest fully closed 15m candle and splits at
missing or discontinuous data.

## Safety and reproducibility

- The full 9.5 GB archive is never downloaded or assembled.
- Only the six selected compressed members are fetched using bounded HTTP ranges.
- Each market is segmented one at a time to limit memory use.
- CSVs, candle arrays, and segment rows remain temporary to the GitHub Actions
  runner; only compact counts and segment date ranges are printed in the log.
- No candles are fabricated, forward-filled, interpolated, or resampled.
- A segment is retained only when it contains at least 200 5m and 200 unique
  contiguous 15m candles.
- This stage reports data availability; it does not run a strategy or backtest.
