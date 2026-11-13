import copy
import unittest

from paper_account import apply_execution, create_account, mark_to_market


def execution(side, qty, price, fee):
    notional = qty * price
    cash_flow = -(notional + fee) if side == "BUY" else notional - fee
    return {
        "ok": True, "symbol": "BTC/USDT", "side": side,
        "filled_quantity": str(qty), "average_fill_price": str(price),
        "gross_notional_usdt": str(notional), "fee_usdt": str(fee),
        "cash_flow_usdt": str(cash_flow),
    }


class PaperAccountTests(unittest.TestCase):
    def test_create_account(self):
        account = create_account("100")
        self.assertEqual(account["cash_usdt"], "100")
        self.assertEqual(account["positions"], {})
        self.assertEqual(account["history"], [])

    def test_buy_includes_fee_in_cost_basis(self):
        account = create_account("100")
        updated = apply_execution(account, execution("BUY", 0.5, 100, 0.05))
        self.assertEqual(updated["cash_usdt"], "49.95")
        self.assertEqual(updated["positions"]["BTC"]["quantity"], "0.5")
        self.assertEqual(updated["positions"]["BTC"]["cost_basis_usdt"], "50.05")
        self.assertEqual(account["cash_usdt"], "100")
        self.assertEqual(account["positions"], {})

    def test_average_cost_across_multiple_buys(self):
        account = create_account("500")
        account = apply_execution(account, execution("BUY", 1, 100, 0.1))
        account = apply_execution(account, execution("BUY", 1, 120, 0.12))
        position = account["positions"]["BTC"]
        self.assertEqual(position["quantity"], "2")
        self.assertEqual(position["cost_basis_usdt"], "220.22")
        self.assertEqual(position["average_cost_usdt"], "110.11")

    def test_partial_sell_realizes_net_profit_and_keeps_average_cost(self):
        account = create_account("500")
        account = apply_execution(account, execution("BUY", 2, 100, 0.2))
        updated = apply_execution(account, execution("SELL", 1, 120, 0.12))
        self.assertEqual(updated["cash_usdt"], "419.68")
        self.assertEqual(updated["positions"]["BTC"]["quantity"], "1")
        self.assertEqual(updated["positions"]["BTC"]["cost_basis_usdt"], "100.1")
        self.assertEqual(updated["realized_pnl_usdt"], "19.78")

    def test_close_position_removes_position(self):
        account = create_account("500")
        account = apply_execution(account, execution("BUY", 1, 100, 0.1))
        account = apply_execution(account, execution("SELL", 1, 110, 0.11))
        self.assertEqual(account["positions"], {})
        self.assertEqual(account["realized_pnl_usdt"], "9.79")

    def test_rejects_oversell_without_mutating_account(self):
        account = create_account("500")
        before = copy.deepcopy(account)
        with self.assertRaisesRegex(ValueError, "insufficient position"):
            apply_execution(account, execution("SELL", 1, 100, 0.1))
        self.assertEqual(account, before)

    def test_rejects_buy_that_exceeds_cash_including_fee(self):
        account = create_account("100")
        before = copy.deepcopy(account)
        with self.assertRaisesRegex(ValueError, "insufficient paper cash"):
            apply_execution(account, execution("BUY", 1, 100, 0.1))
        self.assertEqual(account, before)

    def test_rejects_failed_or_inconsistent_execution(self):
        account = create_account("100")
        failed = execution("BUY", 0.1, 100, 0.01)
        failed["ok"] = False
        with self.assertRaisesRegex(ValueError, "not successful"):
            apply_execution(account, failed)
        inconsistent = execution("BUY", 0.1, 100, 0.01)
        inconsistent["cash_flow_usdt"] = "-1"
        with self.assertRaisesRegex(ValueError, "cash flow"):
            apply_execution(account, inconsistent)

    def test_mark_to_market_reports_equity_and_unrealized_pnl(self):
        account = create_account("500")
        account = apply_execution(account, execution("BUY", 2, 100, 0.2))
        report = mark_to_market(account, {"BTC": "110"})
        self.assertEqual(report["cash_usdt"], "299.8")
        self.assertEqual(report["market_value_usdt"], "220")
        self.assertEqual(report["equity_usdt"], "519.8")
        self.assertEqual(report["unrealized_pnl_usdt"], "19.8")
        self.assertEqual(report["realized_pnl_usdt"], "0")

    def test_mark_to_market_requires_all_marks(self):
        account = create_account("500")
        account = apply_execution(account, execution("BUY", 1, 100, 0.1))
        with self.assertRaisesRegex(ValueError, "missing mark"):
            mark_to_market(account, {})

    def test_supports_separate_asset_positions(self):
        account = create_account("1000")
        btc = execution("BUY", 1, 100, 0.1)
        eth = dict(btc, symbol="ETH/USDT")
        account = apply_execution(account, btc)
        account = apply_execution(account, eth)
        self.assertEqual(set(account["positions"]), {"BTC", "ETH"})


if __name__ == "__main__":
    unittest.main()
