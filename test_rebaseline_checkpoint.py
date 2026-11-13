import json
import unittest

import rebaseline_checkpoint as rb


class RebaselineTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "initial_balance": 100.0,
            "cash_usdt": 99.53596179449755,
            "positions": {},
            "history": [{"symbol": "BTC/USDT", "net_pnl": -0.4469}],
            "last_processed_candle": {
                "BTC/USDT": "1793848200000",
                "ETH/USDT": "1793848200000",
                "SOL/USDT": "1793848200000",
            },
        }
        self.raw = json.dumps(self.state, indent=2).encode()
        self.old_sha = rb.EXPECTED_STATE_BLOB_SHA
        rb.EXPECTED_STATE_BLOB_SHA = rb.git_blob_sha(self.raw)
        self.candles = {}
        for symbol in rb.SYMBOLS:
            self.candles[symbol] = [
                {"timestamp": 1793848200000, "close": 100.0},
                {"timestamp": 1793848500000, "close": 101.0},
                {"timestamp": 1793848800000, "close": 102.0},
            ]

    def tearDown(self):
        rb.EXPECTED_STATE_BLOB_SHA = self.old_sha

    def test_updates_only_checkpoint_and_metadata(self):
        updated, report = rb.build_plan(self.state, self.raw, self.candles)
        self.assertEqual(updated["cash_usdt"], self.state["cash_usdt"])
        self.assertEqual(updated["positions"], {})
        self.assertEqual(updated["history"], self.state["history"])
        self.assertEqual(updated["last_processed_candle"]["BTC/USDT"], "1793848500000")
        self.assertEqual(len(report), 3)

    def test_rejects_open_positions(self):
        state = dict(self.state)
        state["positions"] = {"ETH/USDT": {"entry_price": 1}}
        raw = json.dumps(state, indent=2).encode()
        rb.EXPECTED_STATE_BLOB_SHA = rb.git_blob_sha(raw)
        with self.assertRaises(ValueError):
            rb.build_plan(state, raw, self.candles)

    def test_rejects_stale_or_missing_market_data(self):
        candles = dict(self.candles)
        candles["SOL/USDT"] = []
        with self.assertRaises(ValueError):
            rb.build_plan(self.state, self.raw, candles)

    def test_rejects_changed_state_hash(self):
        with self.assertRaises(ValueError):
            rb.build_plan(self.state, self.raw + b" ", self.candles)


if __name__ == "__main__":
    unittest.main()
