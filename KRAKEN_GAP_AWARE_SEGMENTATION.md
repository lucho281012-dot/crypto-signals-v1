# Kraken gap-aware paired candle segmentation

## Purpose

Split the six real Kraken OHLCVT datasets into continuous, aligned 5m/15m segments suitable for the existing closed-candle strategy adapter.

## Rules

- Input rows must have non-negative, timeframe-aligned, strictly increasing timestamps.
- Each 5m candle is paired only with the latest 15m candle fully closed at that 5m candle's close.
- A segment ends at any missing 5m candle, unavailable required 15m candle, or discontinuity in the selected 15m sequence.
- No missing candle is created, forward-filled, interpolated, resampled, or bridged.
- Each retained segment must contain at least 200 5m and 200 unique contiguous 15m candles by default.
- Output rows are copied; input data are not mutated.
- The output's 5m and 15m arrays can be passed directly to `generate_closed_candle_signal`.

## Output

The module returns paired segments and aggregate metadata including input/usable row counts, segment count, skipped 5m rows without matching 15m data, discontinuity counts, and explicit `candles_fabricated: 0` / `gaps_filled: false` fields.

## Validation

```bash
python -m unittest -v test_kraken_gap_aware_segments.py
python -m unittest -v test_strategy_backtest_adapter.py
```

The isolated GitHub Actions workflow runs both test suites. No market-data files are stored by this change.

## Limitations

This stage defines safe paired segments; it does not yet run the historical datasets through the strategy or backtest engine. The live archive extraction remains temporary to its CI runner, so a subsequent reproducible backtest workflow must repeat extraction and segmentation within the same job or explicitly retain verified datasets as controlled artifacts.

No active paper simulator, state file, live signal rule, credentials, or trading behavior is changed.