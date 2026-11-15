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
            return_value=300000 * 720
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

    def test_allows_missing_cursor_candle_when_kraken_omits_no_trade_interval(self):
        raw = [
            [900000, 3, 4, 2, 3.5, 12],
            [1200000, 4, 5, 3, 4.5, 13],
        ]
        load_markets, markets, milliseconds, fetch = self._mock_exchange(raw)

        with load_markets, markets, milliseconds, fetch:
            candles = market_data.get_candles_since(
                "BTC/USDT",
                since=300000,
                timeframe="5m"
            )

        self.assertEqual([candle["timestamp"] for candle in candles], [900000, 1200000])

    def test_paper_bot_requires_persisted_close_when_kraken_omits_cursor_candle(self):
        import paper_bot

        raw = [
            [900000, 4, 5, 3, 4.5, 2],
        ]
        load_markets, markets, milliseconds, fetch = self._mock_exchange(raw)
        latest = {
            "timestamp": 900000,
            "open": 4,
            "high": 5,
            "low": 3,
            "close": 4.5,
            "volume": 2
        }

        with load_markets, markets, milliseconds, fetch:
            recovered = market_data.get_candles_since(
                "BTC/USDT", since=300000, timeframe="5m"
            )

        with patch("paper_bot.get_candles_since", return_value=recovered):
            with self.assertRaisesRegex(RuntimeError, "cierre persistido"):
                paper_bot.get_pending_candles("BTC/USDT", "300000", latest)

            pending = paper_bot.get_pending_candles(
                "BTC/USDT",
                "300000",
                latest,
                last_processed_close=3.5
            )

        self.assertEqual([candle["timestamp"] for candle in pending], [600000, 900000])
        self.assertEqual(pending[0]["close"], 3.5)

    def test_rejects_empty_ohlc_response(self):
        load_markets, markets, milliseconds, fetch = self._mock_exchange([])

        with load_markets, markets, milliseconds, fetch:
            with self.assertRaisesRegex(
                RuntimeError,
                "no devolvió velas"
            ):
                market_data.get_candles_since(
                    "BTC/USDT",
                    since=600000,
                    timeframe="5m"
                )


    def test_market_data_and_paper_bot_together_reconstruct_no_trade_interval(self):
        import paper_bot

        raw = [
            [300000, 3, 4, 2, 3.5, 7],
            # No 600000 candle: Kraken omits intervals without trades.
            [900000, 4, 5, 3, 4.5, 2],
            # This is a still-open/future candle and must not be processed.
            [1200000, 4.5, 5, 4, 4.8, 1],
        ]
        load_markets, markets, milliseconds, fetch = self._mock_exchange(raw)
        latest_closed = {
            "timestamp": 900000,
            "open": 4,
            "high": 5,
            "low": 3,
            "close": 4.5,
            "volume": 2
        }

        with load_markets, markets, milliseconds, fetch as fetch_mock:
            recovered = market_data.get_candles_since(
                "BTC/USDT",
                since=300000,
                timeframe="5m"
            )
            pending = paper_bot.get_pending_candles(
                "BTC/USDT",
                "300000",
                latest_closed
            )

        self.assertEqual(
            [candle["timestamp"] for candle in recovered],
            [300000, 900000, 1200000]
        )
        self.assertEqual(
            [candle["timestamp"] for candle in pending],
            [600000, 900000]
        )
        self.assertEqual(
            pending[0],
            {
                "timestamp": 600000,
                "open": 3.5,
                "high": 3.5,
                "low": 3.5,
                "close": 3.5,
                "volume": 0.0
            }
        )
        self.assertEqual(pending[-1]["close"], 4.5)
        self.assertEqual(fetch_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
