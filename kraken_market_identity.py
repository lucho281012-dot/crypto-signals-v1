"""Resolve configured CCXT symbols to exact Kraken spot market identifiers.

This is a read-only public-market metadata check. It never places orders.
It deliberately refuses to guess aliases or substitute quote currencies.
"""
import json

DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


def resolve_kraken_spot_markets(exchange, symbols=DEFAULT_SYMBOLS):
    """Return verified market identity records for exact unified symbols."""
    markets = exchange.load_markets()
    resolved = []
    for symbol in symbols:
        market = markets.get(symbol)
        if market is None:
            raise ValueError(f"Kraken no publica el mercado exacto {symbol}")
        if market.get("spot") is not True:
            raise ValueError(f"{symbol}: el mercado encontrado no es spot")
        base, quote = symbol.split("/")
        if market.get("base") != base or market.get("quote") != quote:
            raise ValueError(f"{symbol}: base/quote no coinciden exactamente")
        if market.get("active") is False:
            raise ValueError(f"{symbol}: mercado inactivo")
        market_id = market.get("id")
        if not isinstance(market_id, str) or not market_id:
            raise ValueError(f"{symbol}: Kraken no devolvió un market id")
        resolved.append({
            "exchange": "Kraken",
            "symbol": symbol,
            "market_id": market_id,
            "base": base,
            "quote": quote,
            "spot": True,
            "active": market.get("active"),
        })
    return resolved


def main():
    try:
        import ccxt
    except ImportError as exc:
        raise SystemExit("Instala dependencias con: pip install -r requirements.txt") from exc

    exchange = ccxt.kraken({"enableRateLimit": True})
    try:
        result = resolve_kraken_spot_markets(exchange)
    finally:
        close = getattr(exchange, "close", None)
        if callable(close):
            close()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
