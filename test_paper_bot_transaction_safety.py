import unittest
from unittest.mock import patch

import paper_bot
import paper_trading


def market_payload(low=100.0, open_price=101.0, high=102.0):
    candles_5m = [
        {"timestamp": 100, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0},
        {"timestamp": 200, "open": open_price, "high": high, "low": low, "close": 101.0, "volume": 12.0},
        {"timestamp": 300, "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 8.0},
    ]
    candles_15m = [
        {"timestamp": 0, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 30.0},
        {"timestamp": 900000, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 35.0},
        {"timestamp": 1800000, "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 25.0},
    ]
    return {
        "BTC/USDT": {
            "price": 101.0,
            "candles_5m": candles_5m,
            "candles_15m": candles_15m,
        }
    }


class TransactionSafetyTests(unittest.TestCase):
    def base_state(self):
        return {
            "initial_balance": 100.0,
            "cash_usdt": 100.0,
            "positions": {},
            "history": [],
            "last_processed_candle": {},
        }

    def test_open_position_can_defer_persistence(self):
        state = self.base_state()
        with patch("paper_trading.save_state") as save:
            ok, _ = paper_trading.open_position(
                state, "BTC/USDT", 101.0, 99.8, persist=False
            )
        self.assertTrue(ok)
        self.assertIn("BTC/USDT", state["positions"])
        self.assertLess(state["cash_usdt"], 100.0)
        save.assert_not_called()

    def test_close_position_can_defer_persistence(self):
        state = self.base_state()
        state["cash_usdt"] = 90.0
        state["positions"]["BTC/USDT"] = {
            "entry_price": 100.0,
            "stop_price": 99.0,
            "target_price": 102.0,
            "quantity": 0.1,
            "entry_fee": 0.01,
            "risk_budget": 1.0,
            "opened_at": "2026-11-13T00:00:00+00:00",
        }
        with patch("paper_trading.save_state") as save:
            ok, _ = paper_trading.close_position(
                state, "BTC/USDT", 98.8, "stop_loss", persist=False
            )
        self.assertTrue(ok)
        self.assertNotIn("BTC/USDT", state["positions"])
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["history"][0]["reason"], "stop_loss")
        save.assert_not_called()

    def test_bot_saves_open_position_and_checkpoint_once_together(self):
        state = self.base_state()
        payload = market_payload()

        with patch.object(paper_bot, "load_state", return_value=state), \
             patch.object(paper_bot, "get_all_market_data", return_value=payload), \
             patch.object(paper_bot, "analyze_spot", return_value={"side": "BUY", "atr": 1.0}), \
             patch.object(paper_bot, "save_state") as bot_save, \
             patch("paper_trading.save_state") as trade_save:
            paper_bot.run_bot()

        self.assertIn("BTC/USDT", state["positions"])
        self.assertIn("target_price", state["positions"]["BTC/USDT"])
        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "200")
        bot_save.assert_called_once_with(state)
        trade_save.assert_not_called()

    def test_bot_saves_closed_position_and_checkpoint_once_together(self):
        state = self.base_state()
        state["cash_usdt"] = 90.0
        state["positions"]["BTC/USDT"] = {
            "entry_price": 100.0,
            "stop_price": 99.0,
            "target_price": 105.0,
            "quantity": 0.1,
            "entry_fee": 0.01,
            "risk_budget": 1.0,
            "opened_at": "2026-11-13T00:00:00+00:00",
        }
        payload = market_payload(low=98.5, open_price=98.8, high=100.0)

        with patch.object(paper_bot, "load_state", return_value=state), \
             patch.object(paper_bot, "get_all_market_data", return_value=payload), \
             patch.object(paper_bot, "save_state") as bot_save, \
             patch("paper_trading.save_state") as trade_save:
            paper_bot.run_bot()

        self.assertNotIn("BTC/USDT", state["positions"])
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "200")
        bot_save.assert_called_once_with(state)
        trade_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
