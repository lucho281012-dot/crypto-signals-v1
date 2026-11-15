"""Tests for the read-only connection to the active Paper state model."""
import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import paper_trading
from paper_report_dry_run import build_read_only_report, run_read_only_report


class ReadOnlyPaperReportTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "initial_balance": 1000,
            "cash_usdt": 899.9,
            "positions": {
                "BTC/USDT": {
                    "quantity": 1,
                    "entry_price": 100,
                    "entry_fee": 0.1,
                    "stop_price": 90,
                    "risk_budget": 10,
                    "opened_at": "2026-11-15T10:00:00Z",
                }
            },
            "history": [],
            "last_processed_candle": {"BTC/USDT": "123"},
        }
        self.original_state = copy.deepcopy(self.state)

    def test_builds_report_using_public_price_without_mutating_state(self):
        report = build_read_only_report(
            self.state, {"BTC/USDT": {"price": 110}}
        )
        self.assertEqual(report["equity_usdt"], "1009.9")
        self.assertEqual(report["unrealized_pnl_usdt"], "9.9")
        self.assertEqual(report["open_position_count"], 1)
        self.assertEqual(self.state, self.original_state)

    def test_missing_market_mark_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "missing public market price"):
            build_read_only_report(self.state, {})
        self.assertEqual(self.state, self.original_state)

    def test_empty_portfolio_needs_no_market_data(self):
        state = {
            "initial_balance": 100,
            "cash_usdt": 100,
            "positions": {},
            "history": [],
        }
        report = build_read_only_report(state, {})
        self.assertEqual(report["equity_usdt"], "100")
        self.assertEqual(report["open_position_count"], 0)

    def test_run_skips_network_when_no_positions(self):
        state = {
            "initial_balance": 100,
            "cash_usdt": 100,
            "positions": {},
            "history": [],
        }
        market_module = types.ModuleType("market_data")
        market_module.get_market_price = lambda symbol: self.fail(
            "market price must not be requested for an empty portfolio"
        )
        with patch.dict(sys.modules, {"market_data": market_module}):
            report = run_read_only_report(state=state)
        self.assertEqual(report["equity_usdt"], "100")

    def test_run_fetches_only_ticker_prices_for_open_positions(self):
        market_module = types.ModuleType("market_data")
        requested = []
        def get_market_price(symbol):
            requested.append(symbol)
            return 110
        market_module.get_market_price = get_market_price
        with patch.dict(sys.modules, {"market_data": market_module}):
            report = run_read_only_report(state=self.state)
        self.assertEqual(requested, ["BTC/USDT"])
        self.assertEqual(report["equity_usdt"], "1009.9")
        self.assertEqual(self.state, self.original_state)

    def test_state_reader_does_not_create_missing_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_state = Path(temp_dir) / "missing" / "paper_state.json"
            with patch.object(paper_trading, "STATE_FILE", missing_state):
                report = run_read_only_report(
                    state=None,
                    market_data={},
                )
            self.assertEqual(report["equity_usdt"], "100.0")
            self.assertFalse(missing_state.parent.exists())

    def test_state_reader_reads_file_without_changing_it(self):
        state = {
            "initial_balance": 100,
            "cash_usdt": 100,
            "positions": {},
            "history": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "paper_state.json"
            original = json.dumps(state, sort_keys=True)
            state_file.write_text(original, encoding="utf-8")
            before = state_file.read_bytes()
            with patch.object(paper_trading, "STATE_FILE", state_file):
                report = run_read_only_report(state=None, market_data={})
            self.assertEqual(report["equity_usdt"], "100")
            self.assertEqual(state_file.read_bytes(), before)


    def test_current_simulator_state_reconciles_with_read_only_report(self):
        from decimal import Decimal
        from paper_report_dry_run import _read_state_without_side_effects

        state = _read_state_without_side_effects()
        marks = {
            symbol: {"price": position["entry_price"]}
            for symbol, position in state["positions"].items()
        }
        report = build_read_only_report(state, marks)

        closed = state["history"]
        open_positions = state["positions"]
        expected_realized = sum(
            (Decimal(str(trade["net_pnl"])) for trade in closed),
            Decimal("0"),
        )
        expected_open_fees = sum(
            (
                Decimal(str(position["entry_fee"]))
                for position in open_positions.values()
            ),
            Decimal("0"),
        )
        expected_fees = expected_open_fees + sum(
            (
                Decimal(str(trade["entry_fee"]))
                + Decimal(str(trade["exit_fee"]))
                for trade in closed
            ),
            Decimal("0"),
        )

        self.assertEqual(Decimal(report["cash_usdt"]), Decimal(str(state["cash_usdt"])))
        self.assertEqual(Decimal(report["realized_pnl_usdt"]), expected_realized)
        self.assertEqual(Decimal(report["fees_paid_usdt"]), expected_fees)
        self.assertEqual(report["trade_count"], len(closed))
        self.assertEqual(report["open_position_count"], len(open_positions))
        self.assertEqual(report["buy_count"], len(closed) + len(open_positions))
        self.assertEqual(report["sell_count"], len(closed))

        # At entry-price marks, unrealized P&L is exactly the unpaid/open
        # position entry fees. Float-origin state values can differ by a few
        # machine epsilons, so compare with a tight monetary tolerance.
        expected_total = expected_realized - expected_open_fees
        actual_total = Decimal(report["total_pnl_usdt"])
        self.assertLessEqual(abs(actual_total - expected_total), Decimal("1e-10"))


if __name__ == "__main__":
    unittest.main()
