# Historical backtest foundation

This branch adds only a deterministic execution-cost simulation core. It does
not download historical market data and does not claim strategy profitability.

## Execution contract
- A BUY signal is timestamped at the candle that has already CLOSED.
- Entry is simulated at the NEXT candle open, with adverse buy slippage.
- Position size is bounded by risk budget, maximum exposure and available cash.
- Entry and exit fees are charged.
- Stop/target collisions in one OHLC candle resolve conservatively to stop-loss.
- Gaps through stop/target use the candle open as the raw fill reference, then
  apply adverse slippage.
- An open position at the end of the dataset is liquidated at the final close
  for reporting; this is an explicit end-of-sample convention.

## Not yet implemented
- Signal generation from the repository's 5m/15m strategy.
- Reliable multi-year historical data acquisition and provenance checks.
- Chronological train/validation/test partitioning.
- Spread, funding, exchange-specific precision and market impact.
- Portfolio-level multi-asset concurrency.

Do not interpret synthetic unit-test fixtures as historical performance. Do
not change the active simulator or execute real orders based on this module.
