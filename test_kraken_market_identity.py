import unittest

from kraken_market_identity import resolve_kraken_spot_markets


class FakeKraken:
    def __init__(self, markets):
        self.markets = markets

    def load_markets(self):
        return self.markets


class KrakenMarketIdentityTests(unittest.TestCase):
    def test_resolves_exact_spot_ids_without_rewriting_symbols(self):
        exchange = FakeKraken({
            "BTC/USDT": {"id": "XBTUSDT", "base": "BTC", "quote": "USDT",
                         "spot": True, "active": True},
            "ETH/USDT": {"id": "ETHUSDT", "base": "ETH", "quote": "USDT",
                         "spot": True, "active": True},
        })
        result = resolve_kraken_spot_markets(exchange, ("BTC/USDT", "ETH/USDT"))
        self.assertEqual([row["market_id"] for row in result],
                         ["XBTUSDT", "ETHUSDT"])
        self.assertEqual(result[0]["symbol"], "BTC/USDT")

    def test_rejects_missing_market_instead_of_substituting_quote(self):
        exchange = FakeKraken({
            "BTC/USD": {"id": "XXBTZUSD", "base": "BTC", "quote": "USD",
                        "spot": True, "active": True},
        })
        with self.assertRaisesRegex(ValueError, "mercado exacto BTC/USDT"):
            resolve_kraken_spot_markets(exchange, ("BTC/USDT",))

    def test_rejects_non_spot_market(self):
        exchange = FakeKraken({
            "BTC/USDT": {"id": "BTCUSDT-PERP", "base": "BTC", "quote": "USDT",
                         "spot": False, "active": True},
        })
        with self.assertRaisesRegex(ValueError, "no es spot"):
            resolve_kraken_spot_markets(exchange, ("BTC/USDT",))

    def test_rejects_inactive_market(self):
        exchange = FakeKraken({
            "SOL/USDT": {"id": "SOLUSDT", "base": "SOL", "quote": "USDT",
                         "spot": True, "active": False},
        })
        with self.assertRaisesRegex(ValueError, "inactivo"):
            resolve_kraken_spot_markets(exchange, ("SOL/USDT",))


if __name__ == "__main__":
    unittest.main()
