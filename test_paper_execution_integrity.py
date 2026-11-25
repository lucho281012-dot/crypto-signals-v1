import unittest
from unittest.mock import patch

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
                {"timestamp": 100_000, "open": 90, "high": 91, "low": 89, "close": 90, "volume": 1},
                {"timestamp": 1_000_000, "open": 100, "high": 103, "low": 99, "close": 102, "volume": 2},
                {"timestamp": 1_900_000, "open": 103, "high": 106, "low": 102, "close": 105, "volume": 3},
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
        self.assertEqual(candidate["entry_price"], 105.5)
        self.assertNotEqual(candidate["entry_price"], self.data["candles_5m"][-1]["open"])
        self.assertEqual(candidate["signal_candle_timestamp"], self.signal_candle_ts)
        self.assertEqual(candidate["entry_delay_seconds"], 15.0)
        self.assertEqual(candidate["quote_price"], 105.5)
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


if __name__ == "__main__":
    unittest.main()
