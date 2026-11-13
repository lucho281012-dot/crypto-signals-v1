import json
import unittest

from apply_recovery import EVENTS, build_plan, close_record, git_blob_sha


class RecoveryPlanTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "initial_balance": 100.0,
            "cash_usdt": 94.56557154086417,
            "positions": {
                "ETH/USDT": {
                    "entry_price": 2428.45,
                    "stop_price": 2424.3048571428567,
                    "quantity": 0.0019540261258229456,
                    "entry_fee": 0.004745254745254732,
                    "risk_budget": 0.05,
                    "opened_at": "2026-11-05T01:50:41.725802+00:00",
                    "target_price": 2436.740285714286,
                },
                "SOL/USDT": {
                    "entry_price": 96.06,
                    "stop_price": 95.796,
                    "quantity": 0.0024699431320293194,
                    "entry_fee": 0.00023726273726273642,
                    "risk_budget": 0.0025,
                    "opened_at": "2026-11-05T01:50:41.733198+00:00",
                    "target_price": 96.588,
                },
            },
            "history": [{"symbol": "BTC/USDT", "net_pnl": -0.4469284591358409}],
            "last_processed_candle": {"BTC/USDT": "1793848200000"},
        }
        self.raw = json.dumps(self.state, indent=2).encode("utf-8")

    def test_git_blob_sha_is_stable(self):
        self.assertEqual(len(git_blob_sha(self.raw)), 40)

    def test_eth_and_sol_accounting(self):
        eth = close_record("ETH/USDT", self.state["positions"]["ETH/USDT"], EVENTS["ETH/USDT"])
        sol = close_record("SOL/USDT", self.state["positions"]["SOL/USDT"], EVENTS["SOL/USDT"])
        self.assertAlmostEqual(eth["net_pnl"], -0.017942981682198163, places=12)
        self.assertAlmostEqual(sol["net_pnl"], 0.0008332353155900998, places=12)

    def test_plan_closes_only_reconstructed_positions_and_preserves_checkpoint(self):
        # Patch the expected hash only for this isolated fixture.
        import apply_recovery
        original = apply_recovery.EXPECTED_STATE_BLOB_SHA
        try:
            apply_recovery.EXPECTED_STATE_BLOB_SHA = git_blob_sha(self.raw)
            plan = build_plan(self.state, self.raw)
        finally:
            apply_recovery.EXPECTED_STATE_BLOB_SHA = original

        self.assertEqual(plan["updated_state"]["positions"], {})
        self.assertEqual(len(plan["updated_state"]["history"]), 3)
        self.assertEqual(plan["updated_state"]["last_processed_candle"], self.state["last_processed_candle"])
        self.assertAlmostEqual(plan["cash_after"], 99.53596179449755, places=12)
        self.assertAlmostEqual(plan["realized_pnl_after"], -0.46403820550244895, places=12)

    def test_wrong_state_hash_is_rejected(self):
        with self.assertRaises(ValueError):
            build_plan(self.state, self.raw + b" ")


if __name__ == "__main__":
    unittest.main()
