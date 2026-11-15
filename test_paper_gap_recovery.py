import unittest
from unittest.mock import patch

import paper_bot


class PaperGapRecoveryTests(unittest.TestCase):

    def test_pending_candles_are_sorted_deduplicated_and_closed_only(self):
        recovered = [
            {"timestamp": 300000, "open": 3, "high": 4, "low": 2, "close": 3, "volume": 1},
            {"timestamp": 900000, "open": 9, "high": 10, "low": 8, "close": 9, "volume": 1},
            {"timestamp": 600000, "open": 6, "high": 7, "low": 5, "close": 6, "volume": 1},
            {"timestamp": 600000, "open": 6, "high": 7, "low": 5, "close": 6, "volume": 1},
            {"timestamp": 1200000, "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1},
        ]
        latest = {"timestamp": 900000, "open": 9, "high": 10, "low": 8, "close": 9, "volume": 1}

        with patch("paper_bot.get_candles_since", return_value=recovered):
            pending = paper_bot.get_pending_candles("BTC/USDT", "300000", latest)

        self.assertEqual([c["timestamp"] for c in pending], [600000, 900000])

    def test_pending_candles_reject_incomplete_recovery(self):
        latest = {"timestamp": 900000, "open": 9, "high": 10, "low": 8, "close": 9, "volume": 1}
        recovered = [
            {"timestamp": 300000, "open": 3, "high": 4, "low": 2, "close": 3, "volume": 1},
            {"timestamp": 600000, "open": 6, "high": 7, "low": 5, "close": 6, "volume": 1},
        ]

        with patch("paper_bot.get_candles_since", return_value=recovered):
            with self.assertRaisesRegex(RuntimeError, "última vela cerrada"):
                paper_bot.get_pending_candles("BTC/USDT", "300000", latest)

    def test_no_trade_interval_is_reconstructed_with_zero_volume(self):
        recovered = [
            {"timestamp": 300000, "open": 3, "high": 4, "low": 2, "close": 3.5, "volume": 7},
            {"timestamp": 900000, "open": 4, "high": 5, "low": 3, "close": 4.5, "volume": 2},
        ]
        latest = {"timestamp": 900000, "open": 4, "high": 5, "low": 3, "close": 4.5, "volume": 2}

        with patch("paper_bot.get_candles_since", return_value=recovered):
            pending = paper_bot.get_pending_candles("BTC/USDT", "300000", latest)

        self.assertEqual([c["timestamp"] for c in pending], [600000, 900000])
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

    def test_pending_candles_reject_missing_cursor_seed(self):
        recovered = [
            {"timestamp": 600000, "open": 6, "high": 7, "low": 5, "close": 6, "volume": 1},
            {"timestamp": 900000, "open": 9, "high": 10, "low": 8, "close": 9, "volume": 1},
        ]
        latest = {"timestamp": 900000, "open": 9, "high": 10, "low": 8, "close": 9, "volume": 1}

        with patch("paper_bot.get_candles_since", return_value=recovered):
            with self.assertRaisesRegex(RuntimeError, "vela usada como cursor"):
                paper_bot.get_pending_candles("BTC/USDT", "300000", latest)

    def test_first_run_uses_only_latest_closed_candle(self):
        latest = {"timestamp": 900000, "open": 9, "high": 10, "low": 8, "close": 9, "volume": 1}
        self.assertEqual(
            paper_bot.get_pending_candles("BTC/USDT", None, latest),
            [latest]
        )

    def test_stop_loss_has_priority_if_both_levels_are_touched(self):
        state = {
            "positions": {
                "BTC/USDT": {"stop_price": 95, "target_price": 110}
            }
        }
        candle = {"open": 100, "high": 112, "low": 94}

        with patch("paper_bot.close_position") as close:
            result = paper_bot.process_position_exit(state, "BTC/USDT", candle)

        self.assertEqual(result, "stop_loss")
        close.assert_called_once_with(state, "BTC/USDT", 95, "stop_loss")

    def test_take_profit_is_applied_when_target_is_touched(self):
        state = {
            "positions": {
                "BTC/USDT": {"stop_price": 95, "target_price": 110}
            }
        }
        candle = {"open": 100, "high": 112, "low": 98}

        with patch("paper_bot.close_position") as close:
            result = paper_bot.process_position_exit(state, "BTC/USDT", candle)

        self.assertEqual(result, "take_profit")
        close.assert_called_once_with(state, "BTC/USDT", 110, "take_profit")


if __name__ == "__main__":
    unittest.main()
