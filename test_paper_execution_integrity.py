import unittest
from unittest.mock import patch

import paper_bot
import market_data
from paper_bot import build_entry_candidate


class EntryExecutionIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.signal_candle_ts = 1_000_000
        self.signal_close_ms = self.signal_candle_ts + 300_000
        self.data = {
            "price": 105.5,
            "price_timestamp": self.signal_close_ms + 15_000,
            "candles_5m": [
                {"timestamp": 400_000, "open": 90, "high": 91, "low": 89, "close": 90, "volume": 1},
                {"timestamp": self.signal_candle_ts, "open": 100, "high": 103, "low": 99, "close": 102, "volume": 2},
                {"timestamp": 1_300_000, "open": 103, "high": 106, "low": 102, "close": 105, "volume": 3},
            ],
            "candles_15m": [
                {"timestamp": -900_000, "open": 90, "high": 91, "low": 89, "close": 90, "volume": 1},
                {"timestamp": 0, "open": 100, "high": 103, "low": 99, "close": 102, "volume": 2},
                {"timestamp": 900_000, "open": 103, "high": 106, "low": 102, "close": 105, "volume": 3},
            ],
        }
        self.signal = {
            "side": "BUY", "entry": 102.0, "atr": 2.0,
            "stop": 99.6, "target": 106.8, "rsi": 57.0,
            "conditions_met": 4,
        }

    def test_entry_uses_timestamped_quote_not_current_candle_open(self):
        now = self.signal_close_ms + 20_000
        with patch("paper_bot.analyze_spot", return_value=self.signal):
            candidate = build_entry_candidate(
                {"positions": {}}, "BTC/USDT", self.data, now_ms=now
            )

        self.assertIsNotNone(candidate)
        self.assertAlmostEqual(candidate["entry_price"], 105.55275)
        self.assertNotEqual(candidate["entry_price"], self.data["candles_5m"][-1]["open"])
        self.assertEqual(candidate["signal_candle_timestamp"], self.signal_candle_ts)
        self.assertEqual(candidate["entry_delay_seconds"], 15.0)
        self.assertEqual(candidate["quote_price"], 105.5)
        self.assertEqual(candidate["quote_side"], "ask")
        self.assertEqual(candidate["strategy_version"], "crypto-signals-v1-2")

    def test_quote_before_signal_close_is_rejected(self):
        data = dict(self.data)
        data["price_timestamp"] = self.signal_close_ms - 1
        with patch("paper_bot.analyze_spot", return_value=self.signal):
            candidate = build_entry_candidate(
                {"positions": {}}, "BTC/USDT", data,
                now_ms=self.signal_close_ms + 10_000
            )
        self.assertIsNone(candidate)

    def test_stale_quote_is_rejected(self):
        data = dict(self.data)
        data["price_timestamp"] = self.signal_close_ms + 1_000
        with patch("paper_bot.analyze_spot", return_value=self.signal):
            candidate = build_entry_candidate(
                {"positions": {}}, "BTC/USDT", data,
                now_ms=self.signal_close_ms + 90_000
            )
        self.assertIsNone(candidate)

    def test_future_quote_is_rejected(self):
        data = dict(self.data)
        data["price_timestamp"] = self.signal_close_ms + 20_000
        with patch("paper_bot.analyze_spot", return_value=self.signal):
            candidate = build_entry_candidate(
                {"positions": {}}, "BTC/USDT", data,
                now_ms=self.signal_close_ms + 10_000
            )
        self.assertIsNone(candidate)

    def test_missing_quote_timestamp_is_rejected(self):
        data = dict(self.data)
        data["price_timestamp"] = None
        with patch("paper_bot.analyze_spot", return_value=self.signal):
            candidate = build_entry_candidate(
                {"positions": {}}, "BTC/USDT", data,
                now_ms=self.signal_close_ms + 20_000
            )
        self.assertIsNone(candidate)


    def test_run_bot_batches_all_symbols_before_allocating_risk(self):
        candles_5m = [
            {"timestamp": 300000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
            {"timestamp": 600000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
            {"timestamp": 900000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
        ]
        candles_15m = [
            {"timestamp": 0, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
            {"timestamp": 900000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
            {"timestamp": 1800000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
        ]
        market_data = {
            symbol: {
                "price": 10.0, "price_timestamp": 1_000_000,
                "candles_5m": candles_5m, "candles_15m": candles_15m,
            }
            for symbol in ("BTC/USDT", "ETH/USDT")
        }
        state = {
            "initial_balance": 100.0, "cash_usdt": 100.0,
            "positions": {}, "history": [],
            "last_processed_candle": {}, "last_processed_close": {},
        }
        candidates = [
            {"symbol": "BTC/USDT", "entry_price": 10.0, "stop_price": 9.8},
            {"symbol": "ETH/USDT", "entry_price": 10.0, "stop_price": 9.8},
        ]

        import paper_trading
        persistence_events = []
        with (
            patch("paper_bot.load_state", return_value=state),
            patch("paper_bot.get_all_market_data", return_value=market_data),
            patch("paper_bot.get_pending_candles", side_effect=lambda s, last, latest, close=None: [latest]),
            patch("paper_bot.open_signal_position", side_effect=candidates) as candidate_builder,
            patch("paper_trading.save_state", side_effect=lambda value: persistence_events.append("batch_persist")),
            patch("paper_bot.save_state", side_effect=lambda value: persistence_events.append("cursor_persist")),
            patch("paper_bot.get_status", return_value={"ok": True}),
            patch("builtins.print"),
        ):
            paper_bot.run_bot()

        self.assertEqual(candidate_builder.call_count, 2)
        self.assertEqual(set(state["positions"]), {"BTC/USDT", "ETH/USDT"})
        self.assertEqual(persistence_events, ["batch_persist"])
        self.assertLessEqual(paper_trading.calculate_open_risk(state), 1.0 + 1e-9)
        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "600000")
        self.assertEqual(state["last_processed_candle"]["ETH/USDT"], "600000")


    def test_market_data_fetches_timestamped_ask_after_both_candle_sets(self):
        events = []
        with (
            patch.object(market_data.exchange, "load_markets"),
            patch.object(market_data.exchange, "markets", {"BTC/USDT": {}}),
            patch.object(market_data, "SYMBOLS", ["BTC/USDT"]),
            patch.object(market_data, "get_candles", side_effect=lambda symbol, timeframe: events.append(timeframe) or [{"timestamp": 1}]),
            patch.object(market_data, "get_market_quote", side_effect=lambda symbol: events.append("ask") or (100.25, 1_700_000_000_000)),
            patch("builtins.print"),
        ):
            result = market_data.get_all_market_data()

        self.assertEqual(events, ["5m", "15m", "ask"])
        self.assertEqual(result["BTC/USDT"]["price"], 100.25)
        self.assertEqual(result["BTC/USDT"]["price_timestamp"], 1_700_000_000_000)


    def test_stale_signal_candle_is_rejected_even_with_fresh_quote(self):
        with patch("paper_bot.analyze_spot", return_value=self.signal):
            candidate = build_entry_candidate(
                {"positions": {}}, "BTC/USDT", self.data,
                now_ms=self.signal_close_ms + 300_001
            )
        self.assertIsNone(candidate)

    def test_stale_trend_candle_is_rejected(self):
        with patch("paper_bot.analyze_spot", return_value=self.signal):
            candidate = build_entry_candidate(
                {"positions": {}}, "BTC/USDT", self.data,
                now_ms=self.signal_close_ms + 800_000,
                max_signal_age_ms=1_000_000, max_quote_age_ms=2_000_000
            )
        self.assertIsNone(candidate)


if __name__ == "__main__":
    unittest.main()
