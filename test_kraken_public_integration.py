"""Read-only smoke test against Kraken's public OHLC endpoint.

No API keys, account endpoints, or order methods are used.
"""
from datetime import datetime, timezone

from market_data import exchange, get_candles_since

SYMBOL = "BTC/USDT"
TIMEFRAME = "5m"


def main():
    exchange.load_markets()
    if SYMBOL not in exchange.markets:
        raise RuntimeError(f"{SYMBOL} is not available on Kraken via CCXT")

    recent = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=3)
    if len(recent) < 2:
        raise RuntimeError("Kraken returned too few recent OHLC candles")

    latest_closed = recent[-2]
    since = int(latest_closed[0])
    recovered = get_candles_since(SYMBOL, since, timeframe=TIMEFRAME)

    timestamps = [int(candle["timestamp"]) for candle in recovered]
    if not timestamps or timestamps[0] != since:
        raise AssertionError(
            f"Recent recovery did not start at requested candle: {timestamps[:3]}"
        )
    if timestamps != sorted(set(timestamps)):
        raise AssertionError("Recovered timestamps are not unique and ordered")
    if since not in timestamps:
        raise AssertionError("Requested closed candle is missing")

    print(
        "RECENT_RECOVERY_OK",
        f"first={datetime.fromtimestamp(since / 1000, timezone.utc).isoformat()}",
        f"candles={len(recovered)}",
        f"last={datetime.fromtimestamp(timestamps[-1] / 1000, timezone.utc).isoformat()}",
    )

    # Kraken only exposes its most recent 720 OHLC entries. A request from
    # Unix epoch must therefore be rejected as incomplete, never accepted.
    try:
        get_candles_since(SYMBOL, 0, timeframe=TIMEFRAME)
    except RuntimeError as error:
        if "máximo 720 velas" not in str(error):
            raise
        print("OLD_RANGE_REJECTED_OK", str(error))
    else:
        raise AssertionError(
            "An epoch-to-present request was accepted despite Kraken's OHLC history cap"
        )


if __name__ == "__main__":
    main()
