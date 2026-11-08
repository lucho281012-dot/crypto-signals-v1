
import unittest

from signal_rules import evaluate_signal


class TestSignalRules(unittest.TestCase):

    def test_buy_signal(self):
        data = {
            "close": 77000,
            "ema_50": 76000,
            "rsi_14": 60,
            "atr_14": 150
        }
        self.assertEqual(
            evaluate_signal(data)["signal"], "BUY"
        )

    def test_sell_signal(self):
        data = {
            "close": 75000,
            "ema_50": 76000,
            "rsi_14": 40,
            "atr_14": 150
        }
        self.assertEqual(
            evaluate_signal(data)["signal"], "SELL"
        )

    def test_wait_signal(self):
        data = {
            "close": 75930,
            "ema_50": 76113,
            "rsi_14": 51.05,
            "atr_14": 158.54
        }
        self.assertEqual(
            evaluate_signal(data)["signal"], "WAIT"
        )

    def test_execution_disabled(self):
        data = {
            "close": 77000,
            "ema_50": 76000,
            "rsi_14": 60,
            "atr_14": 150
        }
        result = evaluate_signal(data)
        self.assertEqual(result["execution"], "DISABLED")


if __name__ == "__main__":
    unittest.main()
