import unittest
from unittest.mock import patch

import market_data


class KrakenCandleRecoveryTests(unittest.TestCase):

    def _mock_exchange(self, raw_candles):
        load_markets = patch.object(market_data.exchange, "load_markets")
        markets = patch.object(market_data.exchange, "markets", {"BTC/USDT": {}})
        fetch = patch.object(
            market_data.exchange,
            "fetch_ohlcv",
            return_value=raw_candles
        )
        return load_markets, markets, fetch

    def test_fetch_uses_kraken_limit_and_ccxt_pagination(self):
        raw = [
            [300000, 1, 2, 0.5, 1.5, 10],
            [600000, 2, 3, 1, 2.5, 11],
            [600000, 2, 3, 1, 2.5, 11],
            [900000, 3, 4, 2, 3.5, 12],
        ]
        load_markets, markets, fetch = self._mock_exchange(raw)

        with load_markets, markets, fetch as fetch_mock:
            candles = market_data.get_candles_since(
                "BTC/USDT",
                since=300001,
                timeframe="5m"
            )

        fetch_mock.assert_called_once_with(
            "BTC/USDT",
            timeframe="5m",
            since=300001,
            limit=market_data.KRAKEN_OHLC_MAX_CANDLES,
            params={"paginate": True}
        )
        self.assertEqual(
            [candle["timestamp"] for candle in candles],
            [600000, 900000]
        )

    def test_rejects_range_older_than_first_available_kraken_candle(self):
        raw = [
            [900000, 3, 4, 2, 3.5, 12],
            [1200000, 4, 5, 3, 4.5, 13],
        ]
        load_markets, markets, fetch = self._mock_exchange(raw)

        with load_markets, markets, fetch:
            with self.assertRaisesRegex(
                RuntimeError,
                "máximo 720 velas"
            ):
                market_data.get_candles_since(
                    "BTC/USDT",
                    since=0,
                    timeframe="5m"
                )

    def test_rejects_empty_ohlc_response(self):
        load_markets, markets, fetch = self._mock_exchange([])

        with load_markets, markets, fetch:
            with self.assertRaisesRegex(
                RuntimeError,
                "recibida: ninguna"
            ):
                market_data.get_candles_since(
                    "BTC/USDT",
                    since=600000,
                    timeframe="5m"
                )


if __name__ == "__main__":
    unittest.main()
