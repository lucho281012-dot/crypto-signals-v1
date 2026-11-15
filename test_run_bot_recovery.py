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


    def test_recovered_stop_loss_updates_cash_history_and_cursor_once(self):
        import paper_trading

        state = {
            "initial_balance": 100.0,
            "cash_usdt": 89.99,
            "positions": {
                "BTC/USDT": {
                    "entry_price": 10.0,
                    "stop_price": 8.0,
                    "target_price": 14.0,
                    "quantity": 1.0,
                    "entry_fee": 0.01,
                    "risk_budget": 1.0,
                    "opened_at": "2026-11-15T00:00:00+00:00"
                }
            },
            "history": [],
            "last_processed_candle": {"BTC/USDT": "300000"}
        }
        stop_candle = {
            "timestamp": 600000,
            "open": 9.0,
            "high": 10.0,
            "low": 7.0,
            "close": 8.5,
            "volume": 1.0
        }
        pending = [stop_candle, self.latest]

        with ExitStack() as stack:
            stack.enter_context(patch("paper_bot.load_state", return_value=state))
            stack.enter_context(
                patch("paper_bot.get_all_market_data", return_value=self.market_data)
            )
            save_cursor = stack.enter_context(patch("paper_bot.save_state"))
            stack.enter_context(patch("paper_trading.save_state"))
            stack.enter_context(
                patch("paper_bot.get_pending_candles", return_value=pending)
            )
            open_signal = stack.enter_context(
                patch("paper_bot.open_signal_position")
            )
            stack.enter_context(patch("paper_bot.get_status", return_value={"ok": True}))
            stack.enter_context(patch("builtins.print"))

            paper_bot.run_bot()

            self.assertNotIn("BTC/USDT", state["positions"])
            self.assertEqual(len(state["history"]), 1)
            trade = state["history"][0]
            self.assertEqual(trade["reason"], "stop_loss")
            self.assertEqual(trade["exit_price"], 8.0)
            self.assertAlmostEqual(trade["exit_fee"], 0.008)
            self.assertAlmostEqual(trade["net_pnl"], -2.018)
            self.assertAlmostEqual(state["cash_usdt"], 97.982)
            self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "900000")
            # La entrada, si existe, solo se evalúa en la última vela actual.
            open_signal.assert_called_once_with(
                state, "BTC/USDT", self.market_data["BTC/USDT"]
            )

            # Una segunda ejecución con el cursor actualizado no vuelve a
            # cerrar la posición ni duplica el registro histórico.
            paper_bot.run_bot()

        self.assertEqual(len(state["history"]), 1)
        self.assertAlmostEqual(state["cash_usdt"], 97.982)
        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "900000")
        self.assertEqual(save_cursor.call_count, 2)


    def test_recovered_take_profit_updates_cash_history_and_cursor_once(self):
        import paper_trading

        state = {
            "initial_balance": 100.0,
            "cash_usdt": 89.99,
            "positions": {
                "BTC/USDT": {
                    "entry_price": 10.0,
                    "stop_price": 8.0,
                    "target_price": 12.0,
                    "quantity": 1.0,
                    "entry_fee": 0.01,
                    "risk_budget": 1.0,
                    "opened_at": "2026-11-15T00:00:00+00:00"
                }
            },
            "history": [],
            "last_processed_candle": {"BTC/USDT": "300000"}
        }
        target_candle = {
            "timestamp": 600000,
            "open": 10.0,
            "high": 13.0,
            "low": 9.0,
            "close": 12.5,
            "volume": 1.0
        }
        pending = [target_candle, self.latest]

        with ExitStack() as stack:
            stack.enter_context(patch("paper_bot.load_state", return_value=state))
            stack.enter_context(
                patch("paper_bot.get_all_market_data", return_value=self.market_data)
            )
            save_cursor = stack.enter_context(patch("paper_bot.save_state"))
            save_trade = stack.enter_context(patch("paper_trading.save_state"))
            stack.enter_context(
                patch("paper_bot.get_pending_candles", return_value=pending)
            )
            open_signal = stack.enter_context(
                patch("paper_bot.open_signal_position")
            )
            stack.enter_context(patch("paper_bot.get_status", return_value={"ok": True}))
            stack.enter_context(patch("builtins.print"))

            paper_bot.run_bot()

            self.assertNotIn("BTC/USDT", state["positions"])
            self.assertEqual(len(state["history"]), 1)
            trade = state["history"][0]
            self.assertEqual(trade["reason"], "take_profit")
            self.assertEqual(trade["exit_price"], 12.0)
            self.assertAlmostEqual(trade["exit_fee"], 0.012)
            self.assertAlmostEqual(trade["net_pnl"], 1.978)
            self.assertAlmostEqual(state["cash_usdt"], 101.978)
            self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "900000")
            # Solo se evalúa una posible entrada en la vela más reciente,
            # nunca en la vela histórica que alcanzó el objetivo.
            open_signal.assert_called_once_with(
                state, "BTC/USDT", self.market_data["BTC/USDT"]
            )
            save_trade.assert_called_once()

            # Repetir el ciclo con el cursor actualizado no duplica el cierre.
            paper_bot.run_bot()

        self.assertEqual(len(state["history"]), 1)
        self.assertAlmostEqual(state["cash_usdt"], 101.978)
        self.assertEqual(state["last_processed_candle"]["BTC/USDT"], "900000")
        self.assertEqual(save_cursor.call_count, 2)
        self.assertEqual(save_trade.call_count, 1)


    def test_restart_reloads_persisted_cursor_and_closes_recovered_position_once(self):
        import tempfile
        import paper_trading

        initial_state = {
            "initial_balance": 100.0,
            "cash_usdt": 89.99,
            "positions": {
                "BTC/USDT": {
                    "entry_price": 10.0,
                    "stop_price": 8.0,
                    "target_price": 12.0,
                    "quantity": 1.0,
                    "entry_fee": 0.01,
                    "risk_budget": 1.0,
                    "opened_at": "2026-11-15T00:00:00+00:00"
                }
            },
            "history": [],
            "last_processed_candle": {"BTC/USDT": "300000"}
        }

        first_latest = {
            "timestamp": 600000, "open": 10.0, "high": 11.0,
            "low": 9.0, "close": 10.5, "volume": 1.0
        }
        second_latest = {
            "timestamp": 900000, "open": 8.5, "high": 9.0,
            "low": 7.0, "close": 8.0, "volume": 1.0
        }
        first_data = {"BTC/USDT": {
            "price": 10.5,
            "candles_5m": [
                {"timestamp": 300000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
                first_latest,
                {"timestamp": 900000, "open": 10.5, "high": 11, "low": 10, "close": 10.5, "volume": 1}
            ],
            "candles_15m": self.market_data["BTC/USDT"]["candles_15m"]
        }}
        second_data = {"BTC/USDT": {
            "price": 8.0,
            "candles_5m": [
                {"timestamp": 600000, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1},
                second_latest,
                {"timestamp": 1200000, "open": 8, "high": 9, "low": 7, "close": 8, "volume": 1}
            ],
            "candles_15m": self.market_data["BTC/USDT"]["candles_15m"]
        }}

        with tempfile.TemporaryDirectory() as directory:
            state_path = paper_trading.Path(directory) / "paper_state.json"
            with patch.object(paper_trading, "STATE_FILE", state_path):
                paper_trading.save_state(initial_state)

                with (
                    patch("paper_bot.get_all_market_data", side_effect=[first_data, second_data, second_data]),
                    patch("paper_bot.get_pending_candles", side_effect=[[first_latest], [second_latest]]) as recover,
                    patch("paper_bot.open_signal_position") as open_signal,
                    patch("builtins.print"),
                ):
                    # Proceso 1: avanza el cursor y persiste el estado.
                    paper_bot.run_bot()
                    after_first_run = paper_trading.load_state()
                    self.assertEqual(
                        after_first_run["last_processed_candle"]["BTC/USDT"],
                        "600000"
                    )
                    self.assertIn("BTC/USDT", after_first_run["positions"])
                    self.assertEqual(after_first_run["history"], [])

                    # Proceso 2: carga el archivo persistido y recupera la vela
                    # posterior; el stop se ejecuta una sola vez.
                    paper_bot.run_bot()
                    after_restart = paper_trading.load_state()
                    self.assertNotIn("BTC/USDT", after_restart["positions"])
                    self.assertEqual(len(after_restart["history"]), 1)
                    self.assertEqual(after_restart["history"][0]["reason"], "stop_loss")
                    self.assertAlmostEqual(after_restart["cash_usdt"], 97.982)
                    self.assertEqual(
                        after_restart["last_processed_candle"]["BTC/USDT"],
                        "900000"
                    )

                    # Proceso 3: el cursor evita repetir el cierre.
                    paper_bot.run_bot()
                    final_state = paper_trading.load_state()

                self.assertEqual(len(final_state["history"]), 1)
                self.assertAlmostEqual(final_state["cash_usdt"], 97.982)
                self.assertEqual(recover.call_count, 2)
                open_signal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
