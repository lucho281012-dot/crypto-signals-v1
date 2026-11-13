"""End-to-end in-memory portfolio scenarios using synthetic order books only."""
import copy
import unittest

from paper_account import apply_execution, create_account, mark_to_market
from paper_execution import simulate_market_order


NOW = 2_000_000_000_000
SCENARIOS = {
    "BTC/USDT": {"scale": "100", "buy_qty": "0.1", "sell_qty": "0.04"},
    "ETH/USDT": {"scale": "10", "buy_qty": "1", "sell_qty": "0.4"},
    "SOL/USDT": {"scale": "1", "buy_qty": "10", "sell_qty": "4"},
}


def book_for(symbol, scale):
    scale = float(scale)
    return {
        "symbol": symbol,
        "timestamp_ms": NOW - 100,
        "received_at_ms": NOW - 50,
        "checksum_valid": True,
        "bids": [
            [str(scale * 0.999), "100"],
            [str(scale * 0.998), "100"],
        ],
        "asks": [
            [str(scale * 1.001), "100"],
            [str(scale * 1.002), "100"],
        ],
    }


def execute(account, symbol, side, quantity, scale):
    result = simulate_market_order(book_for(symbol, scale), side, quantity, NOW)
    if not result["ok"]:
        raise AssertionError(f"{symbol} {side} execution rejected: {result['reason']}")
    return apply_execution(account, result), result


class PaperPortfolioScenarioTests(unittest.TestCase):
    def test_buy_all_assets_mark_portfolio_and_partially_sell(self):
        account = create_account("1000")
        original = copy.deepcopy(account)
        buy_results = {}

        for symbol, scenario in SCENARIOS.items():
            account, result = execute(
                account, symbol, "BUY", scenario["buy_qty"], scenario["scale"]
            )
            buy_results[symbol] = result

        self.assertEqual(set(account["positions"]), {"BTC", "ETH", "SOL"})
        self.assertEqual(len(account["history"]), 3)
        self.assertLess(float(account["cash_usdt"]), 1000)
        self.assertEqual(original["cash_usdt"], "1000")
        self.assertEqual(original["positions"], {})

        marks = {
            "BTC": "105",
            "ETH": "10.5",
            "SOL": "1.05",
        }
        valuation_before_sell = mark_to_market(account, marks)
        self.assertGreater(float(valuation_before_sell["market_value_usdt"]), 0)
        self.assertAlmostEqual(
            float(valuation_before_sell["equity_usdt"]),
            float(account["cash_usdt"])
            + float(valuation_before_sell["market_value_usdt"]),
            places=8,
        )
        self.assertEqual(valuation_before_sell["realized_pnl_usdt"], "0")

        for symbol, scenario in SCENARIOS.items():
            account, sell_result = execute(
                account, symbol, "SELL", scenario["sell_qty"], scenario["scale"]
            )
            self.assertTrue(sell_result["ok"])

        self.assertEqual(len(account["history"]), 6)
        for symbol, scenario in SCENARIOS.items():
            base = symbol.split("/")[0]
            expected_remaining = float(scenario["buy_qty"]) - float(scenario["sell_qty"])
            self.assertAlmostEqual(
                float(account["positions"][base]["quantity"]),
                expected_remaining,
                places=10,
            )
        self.assertNotEqual(account["realized_pnl_usdt"], "0")
        final_report = mark_to_market(account, marks)
        self.assertGreater(float(final_report["equity_usdt"]), 0)
        self.assertEqual(
            set(final_report["positions"]), {"BTC", "ETH", "SOL"}
        )

    def test_failed_order_cannot_change_portfolio(self):
        account = create_account("100")
        before = copy.deepcopy(account)
        rejected = simulate_market_order(
            {
                "symbol": "BTC/USDT",
                "timestamp_ms": NOW - 100,
                "received_at_ms": NOW - 50,
                "checksum_valid": True,
                "bids": [["99", "1"]],
                "asks": [["101", "0.01"]],
            },
            "BUY",
            "1",
            NOW,
        )
        self.assertFalse(rejected["ok"])
        with self.assertRaisesRegex(ValueError, "not successful"):
            apply_execution(account, rejected)
        self.assertEqual(account, before)

    def test_insufficient_cash_rejects_buy_without_mutating_portfolio(self):
        account = create_account("1")
        before = copy.deepcopy(account)
        _, result = execute(create_account("100"), "BTC/USDT", "BUY", "0.1", "100")
        with self.assertRaisesRegex(ValueError, "insufficient paper cash"):
            apply_execution(account, result)
        self.assertEqual(account, before)


if __name__ == "__main__":
    unittest.main()
