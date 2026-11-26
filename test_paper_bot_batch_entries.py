import unittest
from unittest.mock import patch

import paper_bot


def market_data(timestamp):
    latest = {"timestamp": timestamp, "open": 10.0, "high": 11.0,
              "low": 9.0, "close": 10.5, "volume": 1.0}
    return {"candles_5m": [
        {"timestamp": timestamp - 600000, "open": 9.0, "high": 10.0,
         "low": 8.0, "close": 9.5, "volume": 1.0},
        latest,
        {"timestamp": timestamp + 300000, "open": 10.5, "high": 11.0,
         "low": 10.0, "close": 10.5, "volume": 1.0}
    ], "candles_15m": []}


class PaperBotBatchEntryTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "initial_balance": 100.0,
            "cash_usdt": 100.0,
            "positions": {},
            "history": [],
            "last_processed_candle": {},
            "last_processed_close": {}
        }
        self.data = {
            "BTC/USDT": market_data(900000),
            "ETH/USDT": market_data(900000)
        }

    def _run(self, batch_return=None, batch_error=None):
        with (
            patch("paper_bot.load_state", return_value=self.state),
            patch("paper_bot.get_all_market_data", return_value=self.data),
            patch("paper_bot.get_pending_candles",
                  side_effect=lambda symbol, last, latest, last_close=None: [latest]),
            patch("paper_bot.process_position_exit", return_value=None),
            patch("paper_bot.open_signal_position", side_effect=[
                {"symbol": "BTC/USDT", "entry_price": 10, "stop_price": 9, "target_price": 12},
                {"symbol": "ETH/USDT", "entry_price": 20, "stop_price": 19, "target_price": 22}
            ]),
            patch("paper_bot.open_positions", return_value=batch_return, side_effect=batch_error) as batch,
            patch("paper_bot.save_state") as save,
            patch("paper_bot.get_status", return_value={}),
            patch("builtins.print")
        ):
            paper_bot.run_bot()
        return batch, save

    def test_all_same_cycle_signals_are_submitted_as_one_batch(self):
        batch, save = self._run(batch_return=[(True, "BTC"), (True, "ETH")])
        batch.assert_called_once()
        self.assertIs(batch.call_args.kwargs["persist"], False)
        save.assert_called_once_with(self.state)
        state_arg, requests_arg = batch.call_args.args
        self.assertIs(state_arg, self.state)
        self.assertEqual([r["symbol"] for r in requests_arg], ["BTC/USDT", "ETH/USDT"])
        self.assertEqual(self.state["last_processed_candle"], {
            "BTC/USDT": "900000", "ETH/USDT": "900000"
        })

    def test_rejected_batch_does_not_advance_latest_cursors(self):
        batch, save = self._run(batch_error=ValueError("batch inválido"))
        batch.assert_called_once()
        self.assertIs(batch.call_args.kwargs["persist"], False)
        save.assert_not_called()
        self.assertEqual(self.state["last_processed_candle"], {})
        self.assertEqual(self.state["last_processed_close"], {})


    def test_rejected_entry_batch_does_not_persist_latest_candle_exit(self):
        import paper_trading

        self.state["cash_usdt"] = 89.99
        self.state["positions"]["BTC/USDT"] = {
            "entry_price": 10.0,
            "stop_price": 9.5,
            "quantity": 1.0,
            "entry_fee": 0.01
        }
        self.data["BTC/USDT"]["candles_5m"][-2]["low"] = 9.0
        rejected_request = {
            "symbol": "ETH/USDT",
            "entry_price": 0.0,
            "stop_price": -1.0,
            "target_price": 2.0
        }

        with (
            patch("paper_bot.load_state", return_value=self.state),
            patch("paper_bot.get_all_market_data", return_value=self.data),
            patch("paper_bot.get_pending_candles",
                  side_effect=lambda symbol, last, latest, last_close=None: [latest]),
            patch("paper_bot.open_signal_position", return_value=rejected_request),
            patch("paper_bot.open_positions", side_effect=ValueError("batch inválido")),
            patch("paper_bot.save_state") as save_cursor,
            patch("paper_trading.save_state") as save_ledger,
            patch("paper_bot.get_status", return_value={}),
            patch("builtins.print")
        ):
            paper_bot.run_bot()

        self.assertNotIn("BTC/USDT", self.state["positions"])
        self.assertEqual(len(self.state["history"]), 1)
        self.assertEqual(self.state["last_processed_candle"], {})
        save_cursor.assert_not_called()
        save_ledger.assert_not_called()


if __name__ == "__main__":
    unittest.main()
