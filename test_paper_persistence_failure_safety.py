import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paper_trading


class PaperPersistenceFailureSafetyTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "initial_balance": 100.0,
            "cash_usdt": 100.0,
            "positions": {},
            "history": [],
        }
        self.candidate = {
            "symbol": "BTC/USDT",
            "entry_price": 10.0,
            "stop_price": 9.8,
        }

    def test_batch_rolls_back_memory_when_state_save_fails(self):
        original_cash = self.state["cash_usdt"]
        original_positions = dict(self.state["positions"])

        with patch("paper_trading.save_state", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                paper_trading.open_positions_batch(self.state, [self.candidate])

        self.assertEqual(self.state["cash_usdt"], original_cash)
        self.assertEqual(self.state["positions"], original_positions)

    def test_failed_atomic_write_preserves_previous_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "paper_state.json"
            previous_state = {"cash_usdt": 77.0, "positions": {}}
            with patch.object(paper_trading, "STATE_FILE", state_path):
                paper_trading.save_state(previous_state)
                previous_bytes = state_path.read_bytes()

                with patch.object(
                    paper_trading.json, "dump",
                    side_effect=TypeError("serialization failed")
                ):
                    with self.assertRaisesRegex(TypeError, "serialization failed"):
                        paper_trading.save_state({"cash_usdt": math.nan})

                self.assertEqual(state_path.read_bytes(), previous_bytes)
                self.assertFalse(state_path.with_suffix(".tmp").exists())

    def test_non_finite_existing_quantity_blocks_new_entries(self):
        for quantity in (math.nan, math.inf, -math.inf):
            with self.subTest(quantity=quantity):
                state = {
                    "initial_balance": 100.0,
                    "cash_usdt": 90.0,
                    "positions": {
                        "ETH/USDT": {
                            "quantity": quantity,
                            "entry_price": 10.0,
                            "stop_price": 9.0,
                        }
                    },
                    "history": [],
                }
                with patch("paper_trading.save_state") as save:
                    result = paper_trading.open_positions_batch(
                        state, [self.candidate]
                    )

                self.assertFalse(result["BTC/USDT"][0])
                self.assertNotIn("BTC/USDT", state["positions"])
                save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
