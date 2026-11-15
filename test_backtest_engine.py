import unittest

from backtest_engine import run_long_backtest


def candles(rows):
    return [
        {"timestamp": i * 300000, "open": row[0], "high": row[1],
         "low": row[2], "close": row[3], "volume": 10}
        for i, row in enumerate(rows)
    ]


class BacktestExecutionTests(unittest.TestCase):
    def test_signal_executes_on_next_open_not_signal_close(self):
        data = candles([(100, 101, 99, 100), (110, 111, 109, 110),
                        (110, 111, 109, 110)])
        result = run_long_backtest(
            data, [{"timestamp": 0, "side": "BUY", "atr": 1}],
            fee_rate=0, slippage_rate=0, risk_percent=0.01,
            max_exposure_percent=0.95
        )
        trade = result["trades"][0]
        self.assertEqual(trade["entry"], 110)
        self.assertEqual(trade["opened_at"], 300000)

    def test_stop_wins_when_stop_and_target_touched_same_candle(self):
        data = candles([(100, 101, 99, 100), (100, 103, 97, 100),
                        (100, 101, 99, 100)])
        result = run_long_backtest(
            data, [{"timestamp": 0, "side": "BUY", "atr": 1}],
            fee_rate=0, slippage_rate=0, stop_atr_multiple=1,
            reward_risk=2
        )
        self.assertEqual(result["trades"][0]["reason"], "stop_loss")
        self.assertEqual(result["trades"][0]["exit_price"], 99)

    def test_fees_and_slippage_reduce_result(self):
        data = candles([(100, 101, 99, 100), (100, 101, 99, 100),
                        (104, 105, 103, 104)])
        signal = [{"timestamp": 0, "side": "BUY", "atr": 1}]
        free = run_long_backtest(data, signal, fee_rate=0, slippage_rate=0)
        costly = run_long_backtest(data, signal, fee_rate=0.001, slippage_rate=0.001)
        self.assertLess(costly["net_pnl"], free["net_pnl"])
        self.assertGreater(costly["fees_paid"], 0)

    def test_rejects_unsorted_or_duplicate_candles(self):
        data = candles([(100, 101, 99, 100), (100, 101, 99, 100)])
        data[1]["timestamp"] = data[0]["timestamp"]
        with self.assertRaisesRegex(ValueError, "únicos y crecientes"):
            run_long_backtest(data, [])

    def test_rejects_signal_without_next_candle(self):
        data = candles([(100, 101, 99, 100), (100, 101, 99, 100)])
        with self.assertRaisesRegex(ValueError, "vela siguiente"):
            run_long_backtest(
                data, [{"timestamp": 300000, "side": "BUY", "atr": 1}]
            )

    def test_final_open_trade_is_closed_at_last_close(self):
        data = candles([(100, 101, 99, 100), (100, 101, 99, 100),
                        (101, 102, 100.5, 101.5)])
        result = run_long_backtest(
            data, [{"timestamp": 0, "side": "BUY", "atr": 5}],
            fee_rate=0, slippage_rate=0
        )
        self.assertEqual(result["trades"][0]["reason"], "end_of_data")
        self.assertFalse(result["open_position_at_end"])


if __name__ == "__main__":
    unittest.main()
