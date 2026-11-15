# Verified Kraken spot market identities

## Live public verification

Verified on 2026-11-15 using CCXT 4.5.92 against Kraken's public market
metadata endpoint. All three exact unified symbols exist, are spot markets,
and are active:

| Configured symbol | Kraken native market ID | Base | Quote | Spot | Active |
|---|---|---|---|---|---|
| BTC/USDT | XBTUSDT | BTC | USDT | yes | yes |
| ETH/USDT | ETHUSDT | ETH | USDT | yes | yes |
| SOL/USDT | SOLUSDT | SOL | USDT | yes | yes |

This confirms the simulator's quote currency is matched exactly: these are
USDT spot markets, not USD substitutions.

## Historical CSV selection

Kraken's OHLCVT archive has one CSV per market and timeframe. The native
market IDs above are the identifiers to match when inspecting the archive
manifest and file list. Expected interval suffixes are `_5.csv` and
`_15.csv`; confirm the actual member names in the downloaded archive before
importing. Do not select files by base asset alone.

For each of the six selected files, record:
- archive filename and archive SHA-256/checksum verification;
- exact member path and timeframe;
- CSV SHA-256 from the importer;
- first/last timestamp and row count;
- missing interval count and first gap;
- whether the 5m/15m series overlap and align.

## Scope

This verification uses public market metadata only. It did not download or
inspect historical OHLCVT files and does not constitute a backtest. No API
keys, private account access, orders, active simulator changes, or paper-state
writes were used.
