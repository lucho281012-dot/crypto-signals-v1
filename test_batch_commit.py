import copy
import unittest

from paper_trading import allocate_batch, commit_batch


def state():
    return {
        "initial_balance": 100.0,
        "cash_usdt": 100.0,
        "positions": {},
        "history": [],
        "last_processed_candle": {},
        "last_processed_close": {},
    }


def signals():
    return [
        {
            "symbol": "BTC/USDT",
            "entry_price": 100.0,
            "stop_price": 98.0,
            "requested_risk": 1.0,
            "target_price": 104.0,
        },
        {
            "symbol": "ETH/USDT",
            "entry_price": 50.0,
            "stop_price": 49.0,
            "requested_risk": 1.0,
            "target_price": 52.0,
        },
    ]


class AtomicBatchCommitTests(unittest.TestCase):

    def test_success_saves_once_then_updates_original_state(self):
        original = state()
        allocations = allocate_batch(original, signals())["allocations"]
        calls = []

        def saver(candidate):
            calls.append(copy.deepcopy(candidate))

        success, message = commit_batch(
            original, allocations, persist_fn=saver
        )

        self.assertTrue(success, message)
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(original["positions"]), {"BTC/USDT", "ETH/USDT"})
        self.assertEqual(
            set(calls[0]["positions"]),
            {"BTC/USDT", "ETH/USDT"},
        )
        self.assertLess(original["cash_usdt"], 100.0)
        self.assertIn("target_price", original["positions"]["BTC/USDT"])

    def test_persistence_failure_leaves_original_state_unchanged(self):
        original = state()
        before = copy.deepcopy(original)
        allocations = allocate_batch(original, signals())["allocations"]

        def failing_saver(candidate):
            raise OSError("simulated disk failure")

        with self.assertRaisesRegex(OSError, "simulated disk failure"):
            commit_batch(original, allocations, persist_fn=failing_saver)

        self.assertEqual(original, before)

    def test_refuses_duplicate_position_without_mutating_state(self):
        original = state()
        allocations = allocate_batch(original, signals())["allocations"]
        original["positions"]["BTC/USDT"] = {
            "entry_price": 100.0,
            "stop_price": 98.0,
            "quantity": 0.01,
            "entry_fee": 0.001,
        }
        before = copy.deepcopy(original)
        calls = []

        success, message = commit_batch(
            original, allocations, persist_fn=lambda candidate: calls.append(candidate)
        )

        self.assertFalse(success)
        self.assertIn("Ya existe", message)
        self.assertEqual(original, before)
        self.assertEqual(calls, [])

    def test_revalidates_aggregate_limits_before_persisting(self):
        original = state()
        oversized = {
            "BTC/USDT": {
                "quantity": 1.0,
                "entry_price": 100.0,
                "stop_price": 98.0,
                "requested_risk": 1.0,
            }
        }
        before = copy.deepcopy(original)
        calls = []

        success, message = commit_batch(
            original,
            oversized,
            persist_fn=lambda candidate: calls.append(candidate),
        )

        self.assertFalse(success)
        self.assertIn("riesgo agregado", message)
        self.assertEqual(original, before)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
