import unittest
from unittest.mock import patch

import pandas as pd

from backtest_strategy_v2 import _close_trade, run_backtest, signal_at
from strategy_v2 import evaluate_buy_signal_at


def market_frame(count=203, spike_last=False):
    rows = []
    for index in range(count):
        op = 100.0
        high, low, close = 100.5, 99.5, 100.0
        if spike_last and index == count - 1:
            high, low = 110.0, 90.0
        rows.append({
            "timestamp": index * 300_000,
            "open": op, "high": high, "low": low, "close": close, "volume": 10.0,
        })
    return pd.DataFrame(rows)


def prepared(count=203, spike_last=False):
    return {"5m": market_frame(count, spike_last)}


class BacktestV2Tests(unittest.TestCase):
    def test_signal_enters_at_next_candle_open_and_liquidates_at_sample_end(self):
        data = {"BTC/USDT": prepared()}
        setup = {"stop_distance": 2.0}
        with patch("backtest_strategy_v2.signal_at", return_value=setup) as signal:
            result = run_backtest(data)
        self.assertEqual(result["closed_trades"], 1)
        trade = result["trade_log"][0]
        self.assertEqual(trade["entry_timestamp"], 201 * 300_000)
        self.assertEqual(trade["reason"], "end_of_sample")
        self.assertEqual(signal.call_args.args[1], 200)

    def test_stop_has_priority_if_stop_and_target_hit_same_candle(self):
        data = {"BTC/USDT": prepared(spike_last=True)}
        with patch("backtest_strategy_v2.signal_at", return_value={"stop_distance": 2.0}):
            result = run_backtest(data)
        trade = result["trade_log"][0]
        self.assertEqual(trade["reason"], "stop_loss")

    def test_portfolio_risk_is_capped_at_one_percent_across_symbols(self):
        data = {"BTC/USDT": prepared(), "ETH/USDT": prepared()}
        with patch("backtest_strategy_v2.signal_at", return_value={"stop_distance": 2.0}):
            result = run_backtest(data)
        entries = [t for t in result["trade_log"] if t["entry_timestamp"] == 201 * 300_000]
        self.assertEqual(len(entries), 1)
        trade = entries[0]
        risk = trade["quantity"] * (
            trade["entry_price"] - trade["stop"]
            + trade["entry_price"] * 0.001 + trade["stop"] * 0.001
        )
        self.assertLessEqual(risk, 1.0 + 1e-9)

    def test_custom_fee_rate_is_used_for_exit_fee(self):
        pos = {
            "quantity": 2.0, "entry": 100.0, "entry_fee": 0.4,
            "entry_cost": 200.4, "stop": 90.0, "target": 120.0,
            "entry_timestamp": 1,
        }
        trade = _close_trade("BTC/USDT", pos, 110.0, 2, "test", 0.002, 0)
        self.assertAlmostEqual(trade["exit_fee"], 0.44)
        self.assertAlmostEqual(trade["net_pnl"], 19.16)


    def test_backtester_signal_adapter_uses_shared_strategy_evaluator(self):
        frames = {"5m": market_frame(203)}
        for timeframe in ("15m", "1h", "4h"):
            frames[timeframe] = pd.DataFrame(columns=[
                "timestamp", "ema20", "ema50", "ema200", "rsi", "macd",
                "macd_signal", "volume_sma20", "atr", "adx", "atr_percent",
                "open", "high", "low", "close", "volume",
            ])
        expected = evaluate_buy_signal_at(frames, 200)
        self.assertIsNone(expected)
        self.assertEqual(signal_at(frames, 200), expected)

    def test_invalid_cost_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            run_backtest({"BTC/USDT": prepared()}, fee_rate=-0.1)
        with self.assertRaises(ValueError):
            run_backtest({"BTC/USDT": prepared()}, slippage_bps=1000)


if __name__ == "__main__":
    unittest.main()
