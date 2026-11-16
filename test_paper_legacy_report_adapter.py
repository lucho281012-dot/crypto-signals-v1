import copy
import unittest

from paper_legacy_report_adapter import build_legacy_paper_report


class LegacyPaperReportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "initial_balance": 1000,
            "cash_usdt": 809.59,
            "positions": {
                "BTC/USDT": {
                    "quantity": 2,
                    "entry_price": 100,
                    "entry_fee": 0.2,
                    "stop_price": 90,
                }
            },
            "history": [{
                "symbol": "ETH/USDT",
                "quantity": 1,
                "entry_price": 100,
                "entry_fee": 0.1,
                "exit_price": 110,
                "exit_fee": 0.11,
                "net_pnl": 9.79,
            }],
        }
        self.marks = {"BTC/USDT": 110}

    def test_builds_canonical_equity_and_pnl_without_double_counting_fees(self):
        report = build_legacy_paper_report(self.state, self.marks)
        self.assertEqual(report["initial_cash_usdt"], "1000")
        self.assertEqual(report["cash_usdt"], "809.59")
        self.assertEqual(report["market_value_usdt"], "220")
        self.assertEqual(report["equity_usdt"], "1029.59")
        self.assertEqual(report["total_pnl_usdt"], "29.59")
        self.assertEqual(report["realized_pnl_usdt"], "9.79")
        self.assertEqual(report["unrealized_pnl_usdt"], "19.8")
        self.assertEqual(report["fees_paid_usdt"], "0.41")
        self.assertEqual(report["trade_count"], 1)
        self.assertEqual(report["buy_count"], 2)
        self.assertEqual(report["sell_count"], 1)
        self.assertEqual(report["open_position_count"], 1)
        self.assertEqual(report["positions"]["BTC"]["market_value_usdt"], "220")
        self.assertEqual(report["positions"]["BTC"]["mark_price_usdt"], "110")

    def test_accepts_base_asset_and_compact_mark_keys(self):
        for key in ("BTC", "BTCUSDT", "BTC/USDT"):
            with self.subTest(mark_key=key):
                report = build_legacy_paper_report(self.state, {key: 110})
                self.assertEqual(report["market_value_usdt"], "220")

    def test_rejects_conflicting_mark_aliases(self):
        with self.assertRaisesRegex(ValueError, "conflicting mark prices"):
            build_legacy_paper_report(
                self.state, {"BTC": 110, "BTC/USDT": 111}
            )

    def test_rejects_duplicate_normalized_positions(self):
        state = copy.deepcopy(self.state)
        state["positions"]["BTCUSDT"] = state["positions"]["BTC/USDT"]
        with self.assertRaisesRegex(ValueError, "duplicate position"):
            build_legacy_paper_report(state, self.marks)

    def test_does_not_mutate_state_or_marks(self):
        state_before = copy.deepcopy(self.state)
        marks_before = copy.deepcopy(self.marks)
        build_legacy_paper_report(self.state, self.marks)
        self.assertEqual(self.state, state_before)
        self.assertEqual(self.marks, marks_before)

    def test_requires_a_mark_for_each_open_position(self):
        with self.assertRaisesRegex(ValueError, "missing mark"):
            build_legacy_paper_report(self.state, {})

    def test_rejects_non_finite_mark(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            build_legacy_paper_report(self.state, {"BTC": float("nan")})

    def test_rejects_unsupported_quote_currency(self):
        state = copy.deepcopy(self.state)
        state["positions"] = {"BTC/USD": state["positions"]["BTC/USDT"]}
        with self.assertRaisesRegex(ValueError, "BASE/USDT"):
            build_legacy_paper_report(state, {"BTC/USD": 110})

    def test_rejects_negative_fees(self):
        state = copy.deepcopy(self.state)
        state["positions"]["BTC/USDT"]["entry_fee"] = -0.1
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            build_legacy_paper_report(state, self.marks)

    def test_requires_explicit_fee_fields(self):
        state = copy.deepcopy(self.state)
        del state["positions"]["BTC/USDT"]["entry_fee"]
        with self.assertRaisesRegex(ValueError, "entry_fee"):
            build_legacy_paper_report(state, self.marks)

    def test_empty_account_has_no_market_value(self):
        state = {
            "initial_balance": 100,
            "cash_usdt": 100,
            "positions": {},
            "history": [],
        }
        report = build_legacy_paper_report(state, {})
        self.assertEqual(report["equity_usdt"], "100")
        self.assertEqual(report["total_pnl_usdt"], "0")
        self.assertEqual(report["open_position_count"], 0)


if __name__ == "__main__":
    unittest.main()
