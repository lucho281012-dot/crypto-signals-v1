"""Deterministic integration-style checks across BTC, ETH and SOL books.

These tests use synthetic data only. They do not connect to an exchange or
read/write the simulator account state.
"""
import unittest

from paper_execution import simulate_market_order


NOW = 2_000_000_000_000
SYMBOLS = {
    "BTC/USDT": "100",
    "ETH/USDT": "10",
    "SOL/USDT": "1",
}
ORDER_SIZES = ("0.25", "0.75", "1.5")


def synthetic_book(symbol, scale):
    scale = float(scale)
    return {
        "symbol": symbol,
        "timestamp_ms": NOW - 100,
        "received_at_ms": NOW - 50,
        "checksum_valid": True,
        "bids": [
            [str(scale * 0.999), "0.5"],
            [str(scale * 0.998), "1.0"],
            [str(scale * 0.997), "2.0"],
        ],
        "asks": [
            [str(scale * 1.001), "0.5"],
            [str(scale * 1.002), "1.0"],
            [str(scale * 1.003), "2.0"],
        ],
    }


class PaperExecutionIntegrationTests(unittest.TestCase):
    def test_buy_and_sell_accounting_invariants_for_all_symbols(self):
        for symbol, scale in SYMBOLS.items():
            with self.subTest(symbol=symbol):
                for side in ("BUY", "SELL"):
                    for quantity in ORDER_SIZES:
                        with self.subTest(side=side, quantity=quantity):
                            book = synthetic_book(symbol, scale)
                            result = simulate_market_order(book, side, quantity, NOW)
                            self.assertTrue(result["ok"], result)
                            self.assertEqual(result["symbol"], symbol)
                            self.assertEqual(result["side"], side)
                            self.assertAlmostEqual(
                                result["filled_quantity"], float(quantity), places=10
                            )

                            fill_notional = sum(
                                fill["price"] * fill["quantity"]
                                for fill in result["fills"]
                            )
                            self.assertAlmostEqual(
                                result["gross_notional_usdt"], fill_notional, places=8
                            )
                            self.assertAlmostEqual(
                                result["average_fill_price"] * result["filled_quantity"],
                                result["gross_notional_usdt"],
                                places=8,
                            )
                            self.assertAlmostEqual(
                                result["fee_usdt"],
                                result["gross_notional_usdt"] * result["fee_rate"],
                                places=8,
                            )

                            if side == "BUY":
                                expected_cash_flow = -(
                                    result["gross_notional_usdt"] + result["fee_usdt"]
                                )
                                self.assertGreaterEqual(
                                    result["average_fill_price"],
                                    result["best_executable_price"],
                                )
                            else:
                                expected_cash_flow = (
                                    result["gross_notional_usdt"] - result["fee_usdt"]
                                )
                                self.assertLessEqual(
                                    result["average_fill_price"],
                                    result["best_executable_price"],
                                )
                            self.assertAlmostEqual(
                                result["cash_flow_usdt"], expected_cash_flow, places=8
                            )
                            self.assertLessEqual(result["levels_consumed"], 3)

    def test_order_sizes_exercise_one_two_and_three_levels(self):
        expected_levels = {"0.25": 1, "0.75": 2, "1.5": 3}
        for symbol, scale in SYMBOLS.items():
            with self.subTest(symbol=symbol):
                for side in ("BUY", "SELL"):
                    for quantity, expected in expected_levels.items():
                        with self.subTest(side=side, quantity=quantity):
                            result = simulate_market_order(
                                synthetic_book(symbol, scale), side, quantity, NOW
                            )
                            self.assertTrue(result["ok"], result)
                            self.assertEqual(result["levels_consumed"], expected)

    def test_rejects_incomplete_depth_for_each_asset_without_partial_fill(self):
        for symbol, scale in SYMBOLS.items():
            with self.subTest(symbol=symbol):
                book = synthetic_book(symbol, scale)
                before = repr(book)
                result = simulate_market_order(book, "BUY", "4", NOW)
                self.assertFalse(result["ok"])
                self.assertIn("insufficient", result["reason"])
                self.assertNotIn("fills", result)
                self.assertEqual(repr(book), before)


if __name__ == "__main__":
    unittest.main()
