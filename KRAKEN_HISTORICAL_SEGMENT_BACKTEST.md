# Historical segment backtest

Runs the existing closed-candle strategy on each independently continuous Kraken
segment. Indicator series are calculated causally over each segment; the first
eligible signal is delayed until at least 200 candles exist in both timeframes.
The 15m row is selected by the 5m candle close, never by a still-forming bar.
The backtest engine executes at the next 5m open with its existing fees,
slippage, stop/target and risk defaults.

Each segment starts with an independent paper balance. Results are aggregated
as pooled trades and equal-allocation segment returns; capital is not compounded
across gaps. This is a historical research result, not a forecast or live-trading
recommendation. No strategy parameters are tuned in this stage.
