import copy
import unittest
from decimal import Decimal

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
        self.assertEqual(report["cash_usdt"], "829.77")
        self.assertEqual(report["market_value_usdt"], "192.50")
        self.assertEqual(report["equity_usdt"], "1022.27")
        self.assertEqual(report["total_pnl_usdt"], "22.27")
        self.assertEqual(report["realized_pnl_usdt"], "4.945")
        self.assertEqual(report["unrealized_pnl_usdt"], "17.325")
        self.assertEqual(report["fees_paid_usdt"], "0.23")
        self.assertEqual(report["trade_count"], 3)
        self.assertEqual(report["buy_count"], 2)
        self.assertEqual(report["sell_count"], 1)
        self.assertEqual(report["open_position_count"], 2)
        self.assertEqual(report["positions"]["BTC"]["quantity"], "0.75")
        self.assertEqual(report["positions"]["ETH"]["quantity"], "10")

        total_pnl = Decimal(report["total_pnl_usdt"])
        realized = Decimal(report["realized_pnl_usdt"])
        unrealized = Decimal(report["unrealized_pnl_usdt"])
        self.assertEqual(total_pnl, realized + unrealized)
        self.assertEqual(
            Decimal(report["total_return_pct"]),
            total_pnl / Decimal(report["initial_cash_usdt"]) * Decimal("100"),
        )

        weights = Decimal(report["cash_weight_pct"]) + sum(
            Decimal(position["portfolio_weight_pct"])
            for position in report["positions"].values()
        )
        self.assertLessEqual(abs(weights - Decimal("100")), Decimal("1e-24"))

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
