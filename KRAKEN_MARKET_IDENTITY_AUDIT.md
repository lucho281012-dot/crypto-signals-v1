# Kraken spot market identity audit

## Purpose
The simulator's configured symbols are BTC/USDT, ETH/USDT and SOL/USDT.
Before selecting historical CSVs, resolve each exact unified symbol against
Kraken's public CCXT market catalogue. Kraken uses native identifiers that can
differ from CCXT symbols (for example, XBT is normalized to BTC), so a CSV
filename must never be guessed from the configured symbol.

## Run
```bash
python kraken_market_identity.py
```

The command calls only Kraken's public market metadata endpoint through CCXT.
It prints the exact unified symbol, native Kraken market id, base/quote, spot
flag and active status. It requires all three exact symbols to exist as spot
markets. It does not silently replace USDT with USD, or substitute another
market. If an exact pair is unavailable, it stops and reports the missing pair.

## Historical-data selection
Use the returned native market id and Kraken archive manifest/file listing to
identify the matching 5m and 15m CSVs. Confirm that both timeframes belong to
the same exact market. Record the archive version, manifest identity, source
CSV hashes, date coverage and gap counts before backtesting.

This check does not download candles, change strategy rules, access private
credentials, place orders, or modify the active Paper simulator/state.
