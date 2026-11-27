import copy
import itertools
import unittest

from paper_trading import allocate_batch


def base_state(cash=100.0, positions=None):
    return {
        "initial_balance": 100.0,
        "cash_usdt": cash,
        "positions": {} if positions is None else positions,
        "history": [],
    }


def signal(symbol, entry=100.0, stop=98.0, requested_risk=1.0):
    return {
        "symbol": symbol,
        "entry_price": entry,
        "stop_price": stop,
        "requested_risk": requested_risk,
    }


class BatchRiskAllocationTests(unittest.TestCase):

    def test_two_simultaneous_signals_share_one_percent_proportionally(self):
        result = allocate_batch(
            base_state(),
            [signal("BTC/USDT"), signal("ETH/USDT")],
        )

        self.assertEqual(set(result["allocations"]), {"BTC/USDT", "ETH/USDT"})
        self.assertAlmostEqual(result["totals"]["risk"], 1.0, places=7)
        self.assertAlmostEqual(
            result["allocations"]["BTC/USDT"]["risk"],
            result["allocations"]["ETH/USDT"]["risk"],
            places=8,
        )

    def test_three_small_demands_do_not_get_scaled_up_to_fill_budget(self):
        result = allocate_batch(
            base_state(),
            [
                signal("BTC/USDT", requested_risk=0.2),
                signal("ETH/USDT", requested_risk=0.2),
                signal("SOL/USDT", requested_risk=0.2),
            ],
        )

        self.assertAlmostEqual(result["totals"]["risk"], 0.6, places=7)

    def test_uses_exit_slippage_and_both_side_fees_in_risk(self):
        result = allocate_batch(base_state(), [signal("BTC/USDT")])
        allocation = result["allocations"]["BTC/USDT"]
        exit_fill = 98.0 * (1 - 5.0 / 10000)
        risk_per_unit = (
            100.0 - exit_fill
            + 100.0 * 0.001
            + exit_fill * 0.001
        )

        self.assertAlmostEqual(
            allocation["risk"],
            allocation["quantity"] * risk_per_unit,
            places=10,
        )

    def test_recalculates_existing_open_risk_instead_of_trusting_saved_budget(self):
        positions = {
            "BTC/USDT": {
                "entry_price": 100.0,
                "stop_price": 98.0,
                "quantity": 0.1,
                "entry_fee": 0.01,
                "risk_budget": 0.0,
            }
        }
        result = allocate_batch(
            base_state(positions=positions),
            [signal("ETH/USDT")],
        )

        expected_open_risk = (
            0.1 * (100.0 - 98.0 * (1 - 5.0 / 10000))
            + 0.01
            + 0.1 * 98.0 * (1 - 5.0 / 10000) * 0.001
        )
        self.assertAlmostEqual(
            result["totals"]["open_risk"], expected_open_risk, places=10
        )
        self.assertAlmostEqual(
            result["totals"]["risk"] + expected_open_risk,
            1.0,
            places=7,
        )

    def test_blocks_entire_batch_if_existing_position_has_no_entry_fee(self):
        positions = {
            "BTC/USDT": {
                "entry_price": 100.0,
                "stop_price": 98.0,
                "quantity": 0.1,
            }
        }
        with self.assertRaisesRegex(ValueError, "sin entry_fee"):
            allocate_batch(base_state(positions=positions), [signal("ETH/USDT")])

    def test_caps_notional_exposure_without_adding_entry_fee_to_exposure(self):
        result = allocate_batch(
            base_state(),
            [signal("BTC/USDT", entry=100.0, stop=99.9)],
        )
        self.assertLessEqual(result["totals"]["exposure"], 95.0 + 1e-9)
        self.assertAlmostEqual(
            result["totals"]["exposure"],
            result["allocations"]["BTC/USDT"]["quantity"] * 100.0,
        )

    def test_caps_cash_including_entry_fee(self):
        result = allocate_batch(
            base_state(cash=5.0),
            [signal("BTC/USDT", entry=10.0, stop=9.0)],
        )
        self.assertLessEqual(result["totals"]["cash_required"], 5.0 + 1e-9)

    def test_rejects_duplicate_and_already_open_symbols(self):
        state = base_state(positions={
            "BTC/USDT": {
                "entry_price": 100.0,
                "stop_price": 98.0,
                "quantity": 0.01,
                "entry_fee": 0.001,
            }
        })
        result = allocate_batch(
            state,
            [
                signal("BTC/USDT"),
                signal("ETH/USDT"),
                signal("ETH/USDT"),
            ],
        )

        self.assertEqual(
            result["rejected"]["BTC/USDT"],
            "ya existe una posición abierta",
        )
        self.assertEqual(
            result["rejected"]["ETH/USDT"],
            "símbolo duplicado en el lote",
        )
        self.assertEqual(set(result["allocations"]), {"ETH/USDT"})

    def test_rejects_invalid_signal_without_mutating_state(self):
        state = base_state()
        original = copy.deepcopy(state)
        result = allocate_batch(
            state,
            [
                signal("BTC/USDT", entry=98.0, stop=100.0),
                signal("ETH/USDT"),
            ],
        )

        self.assertIn("BTC/USDT", result["rejected"])
        self.assertEqual(state, original)
        self.assertIn("ETH/USDT", result["allocations"])

    def test_allocation_is_independent_of_signal_order(self):
        signals = [
            signal("BTC/USDT", entry=100.0, stop=98.0),
            signal("ETH/USDT", entry=50.0, stop=48.0),
            signal("SOL/USDT", entry=25.0, stop=24.0),
        ]
        results = [
            allocate_batch(base_state(), list(order))["allocations"]
            for order in itertools.permutations(signals)
        ]

        for result in results[1:]:
            self.assertEqual(result, results[0])


if __name__ == "__main__":
    unittest.main()
