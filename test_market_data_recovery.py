import unittest
from unittest.mock import patch

import market_data


class KrakenCandleRecoveryTests(unittest.TestCase):

    def _mock_exchange(self, raw_candles):
        load_markets = patch.object(market_data.exchange, "load_markets")
        markets = patch.object(market_data.exchange, "markets", {"BTC/USDT": {}})
        milliseconds = patch.object(
            market_data.exchange,
            "milliseconds",
            return_value=300000 * 1000
        )
        fetch = patch.object(
            market_data.exchange,
            "fetch_ohlcv",
            return_value=raw_candles
        )
        return load_markets, markets, milliseconds, fetch

    def test_fetch_uses_single_kraken_request_without_ccxt_pagination(self):
        raw = [
            [300000, 1, 2, 0.5, 1.5, 10],
            [600000, 2, 3, 1, 2.5, 11],
            [600000, 2, 3, 1, 2.5, 11],
            [900000, 3, 4, 2, 3.5, 12],
        ]
        load_markets, markets, milliseconds, fetch = self._mock_exchange(raw)

        with load_markets, markets, milliseconds, fetch as fetch_mock:
            candles = market_data.get_candles_since(
                "BTC/USDT",
                since=300001,
                timeframe="5m"
            )

        fetch_mock.assert_called_once_with(
            "BTC/USDT",
            timeframe="5m",
            since=300001,
            limit=market_data.KRAKEN_OHLC_MAX_CANDLES
        )
        self.assertEqual(
            [candle["timestamp"] for candle in candles],
            [600000, 900000]
        )

    def test_rejects_too_old_range_before_calling_kraken(self):
        load_markets, markets, milliseconds, fetch = self._mock_exchange([])

        with load_markets, markets, milliseconds, fetch as fetch_mock:
            with self.assertRaisesRegex(
                RuntimeError,
                "fuera del histórico recuperable"
            ):
                market_data.get_candles_since(
                    "BTC/USDT",
                    since=0,
                    timeframe="5m"
                )

        fetch_mock.assert_not_called()

    def test_rejects_incomplete_response_inside_supported_window(self):
        raw = [
            [900000, 3, 4, 2, 3.5, 12],
            [1200000, 4, 5, 3, 4.5, 13],
        ]
        load_markets, markets, milliseconds, fetch = self._mock_exchange(raw)

        with load_markets, markets, milliseconds, fetch:
            with self.assertRaisesRegex(
                RuntimeError,
                "no devolvió la primera vela solicitada"
            ):
                market_data.get_candles_since(
                    "BTC/USDT",
                    since=300000,
                    timeframe="5m"
                )

    def test_rejects_empty_ohlc_response(self):
        load_markets, markets, milliseconds, fetch = self._mock_exchange([])

        with load_markets, markets, milliseconds, fetch:
            with self.assertRaisesRegex(
                RuntimeError,
                "no devolvió la primera vela solicitada"
            ):
                market_data.get_candles_since(
                    "BTC/USDT",
                    since=600000,
                    timeframe="5m"
                )


if __name__ == "__main__":
    unittest.main()
