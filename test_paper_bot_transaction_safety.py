import unittest
from unittest.mock import patch

import paper_bot
import paper_trading


def market_payload(now_ms=2_000_000_000_000, price=101.0):
    payload = {}
    for symbol in paper_bot.SYMBOLS:
        candles = {}
        for timeframe, interval in paper_bot.INTERVAL_MS.items():
            current_open = (now_ms // interval) * interval
            rows = []
            for index in range(250):
                timestamp = current_open - (249 - index) * interval
                rows.append({
                    "timestamp": timestamp,
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 10.0,
                })
            candles[timeframe] = rows
        payload[symbol] = {
            "price": price,
            "price_timestamp": now_ms,
            "candles_5m": candles["5m"],
            "candles_15m": candles["15m"],
        }
    return payload


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
            "entry_price": 100.0, "stop_price": 99.0, "target_price": 102.0,
            "quantity": 0.1, "entry_fee": 0.01, "risk_budget": 1.0,
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
        now_ms = 2_000_000_000_000
        state = self.base_state()
        payload = market_payload(now_ms=now_ms)
        with patch.object(paper_bot, "load_state", return_value=state), \
             patch.object(paper_bot, "get_all_market_data", return_value=payload), \
             patch.object(paper_bot, "analyze_spot", return_value={"side": "BUY", "atr": 1.0}), \
             patch.object(paper_bot, "save_state") as bot_save, \
             patch("paper_trading.save_state") as trade_save:
            paper_bot.run_bot(now_ms=now_ms)
        self.assertIn("BTC/USDT", state["positions"])
        self.assertIn("target_price", state["positions"]["BTC/USDT"])
        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], str(payload["BTC/USDT"]["candles_5m"][-2]["timestamp"]))
        self.assertEqual(bot_save.call_count, 3)
        trade_save.assert_not_called()

    def test_bot_saves_closed_position_and_checkpoint_once_together(self):
        now_ms = 2_000_000_000_000
        state = self.base_state()
        state["cash_usdt"] = 90.0
        state["positions"]["BTC/USDT"] = {
            "entry_price": 100.0, "stop_price": 99.0, "target_price": 105.0,
            "quantity": 0.1, "entry_fee": 0.01, "risk_budget": 1.0,
            "opened_at": "2026-11-13T00:00:00+00:00",
        }
        payload = market_payload(now_ms=now_ms)
        # La vela cerrada toca el stop.
        payload["BTC/USDT"]["candles_5m"][-2]["low"] = 98.5
        payload["BTC/USDT"]["candles_5m"][-2]["open"] = 98.8
        with patch.object(paper_bot, "load_state", return_value=state), \
             patch.object(paper_bot, "get_all_market_data", return_value=payload), \
             patch.object(paper_bot, "save_state") as bot_save, \
             patch("paper_trading.save_state") as trade_save:
            paper_bot.run_bot(now_ms=now_ms)
        self.assertNotIn("BTC/USDT", state["positions"])
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], str(payload["BTC/USDT"]["candles_5m"][-2]["timestamp"]))
        self.assertEqual(bot_save.call_count, 3)
        trade_save.assert_not_called()


class MarketDataValidationTests(unittest.TestCase):
    def test_valid_payload_passes(self):
        now_ms = 2_000_000_000_000
        paper_bot.validate_market_data(market_payload(now_ms), now_ms)

    def test_missing_symbol_rejected_before_state_load(self):
        now_ms = 2_000_000_000_000
        payload = market_payload(now_ms)
        payload.pop("ETH/USDT")
        with patch.object(paper_bot, "load_state") as load:
            with patch.object(paper_bot, "get_all_market_data", return_value=payload):
                with self.assertRaisesRegex(ValueError, "Faltan activos"):
                    paper_bot.run_bot(now_ms=now_ms)
        load.assert_not_called()

    def test_stale_candles_rejected(self):
        now_ms = 2_000_000_000_000
        payload = market_payload(now_ms)
        payload["BTC/USDT"]["candles_5m"][-2]["timestamp"] -= 20 * 60 * 1000
        with self.assertRaisesRegex(ValueError, "desalineada|timestamps"):
            paper_bot.validate_market_data(payload, now_ms)

    def test_missing_candle_interval_rejected(self):
        now_ms = 2_000_000_000_000
        payload = market_payload(now_ms)
        payload["ETH/USDT"]["candles_15m"][-2]["timestamp"] -= 15 * 60 * 1000
        with self.assertRaisesRegex(ValueError, "hueco de velas|timestamps"):
            paper_bot.validate_market_data(payload, now_ms)

    def test_stale_quote_rejected(self):
        now_ms = 2_000_000_000_000
        payload = market_payload(now_ms)
        payload["SOL/USDT"]["price_timestamp"] -= 3 * 60 * 1000
        with self.assertRaisesRegex(ValueError, "cotización desactualizada"):
            paper_bot.validate_market_data(payload, now_ms)

    def test_entry_drift_skips_trade_but_checkpoints(self):
        now_ms = 2_000_000_000_000
        state = self.base_state()
        payload = market_payload(now_ms, price=102.0)  # 1.49% sobre cierre 100.5
        with patch.object(paper_bot, "load_state", return_value=state), \
             patch.object(paper_bot, "get_all_market_data", return_value=payload), \
             patch.object(paper_bot, "analyze_spot", return_value={"side": "BUY", "atr": 1.0}), \
             patch.object(paper_bot, "save_state"):
            paper_bot.run_bot(now_ms=now_ms)
        self.assertNotIn("BTC/USDT", state["positions"])
        self.assertIn("BTC/USDT", state["last_processed_candle"])


if __name__ == "__main__":
    unittest.main()
