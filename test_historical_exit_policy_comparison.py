import unittest

from backtest_engine import run_long_backtest
from historical_exit_policy_comparison import (
    POLICIES, _run_policy, compare_exit_policies, aggregate_exit_policy_folds,
)


def candles(rows):
    return [
        {"timestamp": i * 300_000, "open": o, "high": h, "low": l,
         "close": c, "volume": 10}
        for i, (o, h, l, c) in enumerate(rows)
    ]


class ExitPolicyComparisonTests(unittest.TestCase):
    def test_baseline_is_exactly_the_existing_backtest(self):
        bars = candles([
            (100, 101, 99, 100),
            (100, 101, 99.5, 100.5),
            (100.5, 103, 100, 102),
            (102, 103, 101, 102),
        ])
        signals = [{"timestamp": 0, "side": "BUY", "atr": 1}]
        baseline = run_long_backtest(bars, signals)
        compared = compare_exit_policies(bars, signals)["baseline"]
        self.assertEqual(compared["trade_count"], baseline["trade_count"])
        self.assertAlmostEqual(compared["net_pnl"], baseline["net_pnl"])
        self.assertAlmostEqual(compared["fees_paid"], baseline["fees_paid"])
        self.assertEqual(compared["wins"], sum(t["net_pnl"] > 0 for t in baseline["trades"]))

    def test_stop_wins_when_stop_and_favorable_levels_share_one_candle(self):
        bars = candles([
            (100, 100.5, 99.5, 100),
            (100, 103, 97, 101),
        ])
        signals = [{"timestamp": 0, "side": "BUY", "atr": 1}]
        for policy in POLICIES[1:]:
            result = _run_policy(bars, signals, policy)
            self.assertEqual(result["trades"][0]["reason"], "stop_loss")

    def test_partial_exit_books_only_realized_quantity_once(self):
        bars = candles([
            (100, 100.5, 99.5, 100),
            (100, 101.5, 99.5, 101),
            (101, 101.2, 98.5, 99),
        ])
        signals = [{"timestamp": 0, "side": "BUY", "atr": 1}]
        result = _run_policy(bars, signals, "partial_50_at_1r")
        self.assertEqual(result["trade_count"], 1)
        self.assertEqual(result["trades"][0]["reason"], "stop_loss")
        self.assertGreater(result["trades"][0]["net_pnl"], -1.0)
        self.assertLess(result["trades"][0]["net_pnl"], 0.0)

    def test_stop_updates_from_bar_high_only_apply_on_next_bar(self):
        bars = candles([
            (100, 100.5, 99.5, 100),
            (100, 101.5, 99.5, 101),
            (101, 101.2, 100.1, 100.5),
        ])
        signals = [{"timestamp": 0, "side": "BUY", "atr": 1}]
        result = _run_policy(bars, signals, "breakeven_1r")
        # The trigger bar's low does not retroactively hit the newly moved stop.
        self.assertEqual(result["trades"][0]["reason"], "end_of_data")

    def test_aggregates_independent_folds_without_compounding(self):
        row = {name: {
            "trade_count": 2, "wins": 1, "losses": 1, "net_pnl": -1.0,
            "gross_profit": 1.0, "gross_loss": 2.0, "fees_paid": 0.1,
            "max_drawdown_percent": 2.0,
        } for name in POLICIES}
        result = aggregate_exit_policy_folds([row, row], initial_balance=100)
        self.assertEqual(result["baseline"]["folds"], 2)
        self.assertEqual(result["baseline"]["trade_count"], 4)
        self.assertAlmostEqual(result["baseline"]["equal_allocation_return_percent"], -0.5)


if __name__ == "__main__":
    unittest.main()
