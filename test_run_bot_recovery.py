import unittest
from contextlib import ExitStack
from unittest.mock import patch

import paper_bot


class RunBotRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.latest = {
            "timestamp": 900000,
            "open": 9,
            "high": 10,
            "low": 8,
            "close": 9,
            "volume": 1
        }
        self.market_data = {
            "BTC/USDT": {
                "price": 9,
                "candles_5m": [
                    {"timestamp": 600000, "open": 6, "high": 7, "low": 5, "close": 6, "volume": 1},
                    self.latest,
                    {"timestamp": 1200000, "open": 9, "high": 10, "low": 8, "close": 9, "volume": 1}
                ],
                "candles_15m": [
                    {"timestamp": 0, "open": 8, "high": 9, "low": 7, "close": 8, "volume": 1}
                ]
            }
        }

    def _run_with_mocks(self, state, pending=None, recovery_error=None):
        with ExitStack() as stack:
            stack.enter_context(patch("paper_bot.load_state", return_value=state))
            stack.enter_context(
                patch("paper_bot.get_all_market_data", return_value=self.market_data)
            )
            save_state = stack.enter_context(patch("paper_bot.save_state"))
            stack.enter_context(
                patch("paper_bot.get_status", return_value={"ok": True})
            )
            stack.enter_context(patch("builtins.print"))
            process_exit = stack.enter_context(
                patch("paper_bot.process_position_exit")
            )
            open_signal = stack.enter_context(
                patch("paper_bot.open_signal_position")
            )

            if recovery_error is not None:
                recovery = patch(
                    "paper_bot.get_pending_candles",
                    side_effect=recovery_error
                )
            else:
                recovery = patch(
                    "paper_bot.get_pending_candles",
                    return_value=pending
                )
            stack.enter_context(recovery)

            paper_bot.run_bot()

        return save_state, process_exit, open_signal

    def test_gap_processes_each_recovered_candle_but_opens_only_once_at_latest(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 100.0,
            "positions": {},
            "history": [],
            "last_processed_candle": {"BTC/USDT": "300000"}
        }
        pending = [
            {"timestamp": 600000, "open": 6, "high": 7, "low": 5, "close": 6, "volume": 1},
            self.latest
        ]

        save, exits, opens = self._run_with_mocks(state, pending=pending)

        self.assertEqual(
            [call.args[2]["timestamp"] for call in exits.call_args_list],
            [600000, 900000]
        )
        opens.assert_called_once_with(state, "BTC/USDT", self.market_data["BTC/USDT"])
        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "900000")
        self.assertEqual(save.call_count, 2)

    def test_recovery_failure_does_not_advance_cursor_or_save_state(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 100.0,
            "positions": {},
            "history": [],
            "last_processed_candle": {"BTC/USDT": "300000"}
        }

        save, exits, opens = self._run_with_mocks(
            state,
            recovery_error=RuntimeError("temporary API failure")
        )

        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "300000")
        save.assert_not_called()
        exits.assert_not_called()
        opens.assert_not_called()

    def test_existing_position_is_checked_on_each_recovered_candle(self):
        state = {
            "initial_balance": 100.0,
            "cash_usdt": 90.0,
            "positions": {
                "BTC/USDT": {
                    "entry_price": 10,
                    "stop_price": 8,
                    "quantity": 1,
                    "entry_fee": 0.01
                }
            },
            "history": [],
            "last_processed_candle": {"BTC/USDT": "300000"}
        }
        pending = [
            {"timestamp": 600000, "open": 6, "high": 7, "low": 5, "close": 6, "volume": 1},
            self.latest
        ]

        save, exits, opens = self._run_with_mocks(state, pending=pending)

        self.assertEqual(exits.call_count, 2)
        # La posición estaba abierta al llegar a la última vela: no se abre
        # otra entrada sobre el mismo ciclo de recuperación.
        opens.assert_not_called()
        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "900000")
        self.assertEqual(save.call_count, 2)


if __name__ == "__main__":
    unittest.main()
