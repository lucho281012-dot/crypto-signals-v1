import unittest

from historical_trade_excursions import diagnose_trade_excursions


class TradeExcursionTests(unittest.TestCase):
    def test_calculates_excursions_and_holding_time(self):
        candles = [
            {"timestamp": 0, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"timestamp": 300000, "open": 100, "high": 104, "low": 98, "close": 102, "volume": 1},
            {"timestamp": 600000, "open": 102, "high": 103, "low": 99, "close": 100, "volume": 1},
        ]
        trades = [{
            "opened_at": 0, "closed_at": 600000, "entry": 100,
            "stop": 98, "net_pnl": -1, "reason": "stop_loss",
        }]
        result = diagnose_trade_excursions(candles, trades)
        self.assertEqual(result["trade_count"], 1)
        self.assertEqual(result["avg_hold_minutes"], 10)
        self.assertEqual(result["avg_mfe_r"], 2)
        self.assertEqual(result["avg_mae_r"], 1)
        self.assertEqual(result["mfe_threshold_counts"]["at_least_2R"], 1)
        self.assertEqual(result["exit_reason_counts"], {"stop_loss": 1})

    def test_empty_trades_return_zero_summary(self):
        result = diagnose_trade_excursions([], [])
        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(result["avg_mfe_r"], 0)

    def test_rejects_unmapped_trade_timestamps(self):
        with self.assertRaises(ValueError):
            diagnose_trade_excursions([], [{
                "opened_at": 0, "closed_at": 1, "entry": 100,
                "stop": 99, "net_pnl": 0, "reason": "unknown",
            }])

    def test_groups_excursions_by_exit_reason(self):
        candles = [
            {"timestamp": 0, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"timestamp": 300000, "open": 100, "high": 103, "low": 99, "close": 102, "volume": 1},
            {"timestamp": 600000, "open": 102, "high": 103, "low": 100, "close": 102, "volume": 1},
            {"timestamp": 900000, "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1},
        ]
        trades = [
            {"opened_at": 0, "closed_at": 600000, "entry": 100, "stop": 98,
             "net_pnl": -1, "reason": "stop_loss"},
            {"opened_at": 600000, "closed_at": 900000, "entry": 102, "stop": 100,
             "net_pnl": 2, "reason": "take_profit"},
        ]
        result = diagnose_trade_excursions(candles, trades)
        self.assertEqual(result["by_exit_reason"]["stop_loss"]["trade_count"], 1)
        self.assertEqual(result["by_exit_reason"]["take_profit"]["trade_count"], 1)
        self.assertAlmostEqual(result["by_exit_reason"]["take_profit"]["avg_mfe_r"], 1)


if __name__ == "__main__":
    unittest.main()
