import unittest
from contextlib import ExitStack
from unittest.mock import patch

from market_data import SYMBOLS
import paper_bot


def candle(timestamp, price=100.0):
    return {
        "timestamp": timestamp,
        "open": price,
        "high": price + 1,
        "low": price - 1,
        "close": price,
        "volume": 10.0,
    }


def synchronized_market_data():
    data = {}
    for index, symbol in enumerate(SYMBOLS):
        price = 100.0 + index
        data[symbol] = {
            "price": price,
            "candles_5m": [
                candle(300000, price),
                candle(600000, price),
                candle(900000, price),
            ],
            "candles_15m": [
                candle(0, price),
                candle(900000, price),
            ],
        }
    return data


class EntryRoundBarrierIntegrationTests(unittest.TestCase):
    """Una ronda incompleta no puede abrir posiciones en ningún símbolo."""

    def setUp(self):
        self.market_data = synchronized_market_data()
        self.state = {
            "initial_balance": 100.0,
            "cash_usdt": 100.0,
            "positions": {},
            "history": [],
            "last_processed_candle": {
                symbol: "300000" for symbol in SYMBOLS
            },
            "last_processed_close": {
                symbol: 100.0 for symbol in SYMBOLS
            },
        }
        self.pending = {
            symbol: [candle(600000, 100.0 + index)]
            for index, symbol in enumerate(SYMBOLS)
        }

    def run_round(self, recovery):
        with ExitStack() as stack:
            stack.enter_context(
                patch("paper_bot.load_state", return_value=self.state)
            )
            stack.enter_context(
                patch(
                    "paper_bot.get_all_market_data",
                    return_value=self.market_data,
                )
            )
            stack.enter_context(
                patch("paper_bot.validate_entry_round", return_value={})
            )
            stack.enter_context(
                patch("paper_bot.get_pending_candles", side_effect=recovery)
            )
            stack.enter_context(patch("paper_bot.save_state"))
            stack.enter_context(
                patch("paper_bot.get_status", return_value={"ok": True})
            )
            stack.enter_context(patch("builtins.print"))
            exits = stack.enter_context(
                patch("paper_bot.process_position_exit")
            )
            entries = stack.enter_context(
                patch("paper_bot.open_signal_position")
            )

            paper_bot.run_bot()

        return entries, exits

    def test_one_symbol_recovery_failure_blocks_all_new_entries(self):
        failed_symbol = SYMBOLS[1]

        def recovery(symbol, *args):
            if symbol == failed_symbol:
                raise RuntimeError("temporary recovery failure")
            return self.pending[symbol]

        entries, _ = self.run_round(recovery)

        entries.assert_not_called()

    def test_symbol_without_new_candle_blocks_all_new_entries(self):
        stale_symbol = SYMBOLS[1]
        self.state["last_processed_candle"][stale_symbol] = "600000"

        def recovery(symbol, *args):
            return self.pending[symbol]

        entries, _ = self.run_round(recovery)

        entries.assert_not_called()

    def test_multiple_pending_candles_in_one_symbol_block_all_new_entries(self):
        delayed_symbol = SYMBOLS[2]
        self.state["last_processed_candle"][delayed_symbol] = "0"
        self.pending[delayed_symbol] = [
            candle(300000, 102.0),
            candle(600000, 102.0),
        ]

        def recovery(symbol, *args):
            return self.pending[symbol]

        entries, _ = self.run_round(recovery)

        entries.assert_not_called()

    def test_fully_synchronized_round_allows_entry_evaluation(self):
        def recovery(symbol, *args):
            return self.pending[symbol]

        entries, _ = self.run_round(recovery)

        self.assertEqual(entries.call_count, len(SYMBOLS))
        self.assertEqual(
            {call.args[1] for call in entries.call_args_list},
            set(SYMBOLS),
        )


if __name__ == "__main__":
    unittest.main()
