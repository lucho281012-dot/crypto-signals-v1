# Strategy-to-backtest integration adapter

## Scope
This isolated adapter connects the existing 5m/15m spot signal engine to the
historical execution core. It accepts already-closed OHLCV candles only and
returns a timestamped BUY signal for execution by the next 5m candle open.

## Leakage controls
- Candle timestamps are UTC milliseconds and represent candle OPEN times.
- Both series must contain at least 200 candles, be strictly contiguous, unique,
  ordered, and aligned to their timeframe.
- The latest 15m candle must be the most recent fully closed 15m candle available
  at the close of the latest 5m candle.
- A private duplicate sentinel adapts the live engine's intentional iloc[-2]
  convention without changing signal_engine.py or the supplied input arrays.
- The adapter never fills missing candles or reads any future candle.
- A signal timestamp points to the source 5m candle; the execution engine enters
  at the following candle open.

## Limitations
This is an integration adapter, not a historical backtest result. No historical
dataset is downloaded or authenticated here. No profitability claim is made.
Dataset exchange, provenance, checksum, train/validation/test splits, and
multi-symbol portfolio behavior remain future work. Missing intervals are
rejected; they must not be synthesized for this strategy because fabricated
zero-volume candles can alter volume indicators.
