import copy
import unittest

from paper_account import apply_execution, create_account
from paper_report import build_performance_report


def execution(symbol, side, quantity, price, fee):
    notional = quantity * price
    cash_flow = -(notional + fee) if side == "BUY" else notional - fee
    return {
        "ok": True, "symbol": symbol, "side": side,
        "filled_quantity": str(quantity), "average_fill_price": str(price),
        "gross_notional_usdt": str(notional), "fee_usdt": str(fee),
        "cash_flow_usdt": str(cash_flow),
    }


class PaperPerformanceReportTests(unittest.TestCase):
    def test_report_calculates_equity_return_fees_and_positions(self):
        account = create_account("1000")
        account = apply_execution(account, execution("BTC/USDT", "BUY", 1, 100, 0.1))
        account = apply_execution(account, execution("ETH/USDT", "BUY", 10, 10, 0.1))
        account = apply_execution(account, execution("BTC/USDT", "SELL", 0.25, 120, 0.03))

        report = build_performance_report(account, {"BTC": "110", "ETH": "11"})

        self.assertEqual(report["initial_cash_usdt"], "1000")
        self.assertEqual(report["fees_paid_usdt"], "0.23")
        self.assertEqual(report["trade_count"], 3)
        self.assertEqual(report["buy_count"], 2)
        self.assertEqual(report["sell_count"], 1)
        self.assertEqual(report["open_position_count"], 2)
        self.assertEqual(report["positions"]["BTC"]["quantity"], "0.75")
        self.assertEqual(report["positions"]["ETH"]["quantity"], "10")
        self.assertEqual(
            float(report["total_pnl_usdt"]),
            float(report["realized_pnl_usdt"]) + float(report["unrealized_pnl_usdt"]),
            places=8,
        )
        self.assertGreater(float(report["total_return_pct"]), 0)

    def test_empty_account_reports_initial_cash_and_zero_return(self):
        account = create_account("250")
        report = build_performance_report(account, {})
        self.assertEqual(report["equity_usdt"], "250")
        self.assertEqual(report["total_pnl_usdt"], "0")
        self.assertEqual(report["total_return_pct"], "0")
        self.assertEqual(report["cash_weight_pct"], "100")
        self.assertEqual(report["open_position_count"], 0)

    def test_report_does_not_mutate_account_or_marks(self):
        account = create_account("500")
        account = apply_execution(account, execution("BTC/USDT", "BUY", 1, 100, 0.1))
        marks = {"BTC": "105"}
        account_before = copy.deepcopy(account)
        marks_before = copy.deepcopy(marks)
        build_performance_report(account, marks)
        self.assertEqual(account, account_before)
        self.assertEqual(marks, marks_before)

    def test_missing_position_mark_is_rejected(self):
        account = create_account("500")
        account = apply_execution(account, execution("BTC/USDT", "BUY", 1, 100, 0.1))
        with self.assertRaisesRegex(ValueError, "missing mark"):
            build_performance_report(account, {})

    def test_invalid_history_fee_is_rejected(self):
        account = create_account("500")
        account["history"] = [{
            "side": "BUY", "fee_usdt": "NaN",
        }]
        with self.assertRaisesRegex(ValueError, "finite"):
            build_performance_report(account, {})

    def test_unknown_trade_side_is_rejected(self):
        account = create_account("500")
        account["history"] = [{"side": "HOLD", "fee_usdt": "0"}]
        with self.assertRaisesRegex(ValueError, "side"):
            build_performance_report(account, {})


if __name__ == "__main__":
    unittest.main()
