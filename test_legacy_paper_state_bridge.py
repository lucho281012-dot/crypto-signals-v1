import copy
import json
from pathlib import Path
import tempfile
import unittest

from export_legacy_paper_state import build_legacy_state_report, export_state_json, main


class LegacyPaperStateBridgeTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "initial_balance": "1000",
            "cash_usdt": "700",
            "positions": {
                "BTC/USDT": {
                    "entry_price": "50000",
                    "stop_price": "49000",
                    "quantity": "0.005",
                    "entry_fee": "0.25",
                }
            },
            "history": [{
                "symbol": "ETH/USDT",
                "entry_fee": "0.10",
                "exit_fee": "0.10",
                "net_pnl": "4.80",
            }],
            "last_processed_candle": {"BTC/USDT": "123"},
        }
        self.marks = {"BTC": "52000"}

    def test_report_uses_read_only_state_and_separate_marks(self):
        original = copy.deepcopy(self.state)
        report = build_legacy_state_report(self.state, self.marks)
        self.assertEqual(self.state, original)
        self.assertEqual(report["cash_usdt"], "700")
        self.assertEqual(report["market_value_usdt"], "260.000")
        self.assertEqual(report["equity_usdt"], "960.000")
        self.assertEqual(report["total_pnl_usdt"], "-40.000")
        self.assertEqual(report["realized_pnl_usdt"], "4.80")
        self.assertEqual(report["fees_paid_usdt"], "0.45")
        self.assertEqual(report["positions"]["BTC"]["quantity"], "0.005")
        self.assertEqual(report["trade_count"], 1)
        self.assertEqual(report["buy_count"], 1)
        self.assertEqual(report["sell_count"], 1)

    def test_accepts_all_symbols_used_by_paper_simulator(self):
        state = copy.deepcopy(self.state)
        state["positions"] = {
            "BTC/USDT": {"entry_price": "50000", "quantity": "0.001", "entry_fee": "0.05"},
            "ETH/USDT": {"entry_price": "3000", "quantity": "0.01", "entry_fee": "0.03"},
            "SOL/USDT": {"entry_price": "100", "quantity": "0.5", "entry_fee": "0.05"},
        }
        report = build_legacy_state_report(
            state, {"BTC": "51000", "ETH": "3100", "SOL": "105"}
        )
        self.assertEqual(set(report["positions"]), {"BTC", "ETH", "SOL"})
        self.assertEqual(report["open_position_count"], 3)
        self.assertEqual(report["market_value_usdt"], "153.000")

    def test_accepts_compact_legacy_symbol(self):
        state = copy.deepcopy(self.state)
        state["positions"] = {"BTCUSDT": state["positions"]["BTC/USDT"]}
        report = build_legacy_state_report(state, self.marks)
        self.assertIn("BTC", report["positions"])

    def test_rejects_duplicate_normalized_assets(self):
        state = copy.deepcopy(self.state)
        state["positions"]["BTCUSDT"] = state["positions"]["BTC/USDT"]
        with self.assertRaisesRegex(ValueError, "duplicate position"):
            build_legacy_state_report(state, self.marks)

    def test_rejects_malformed_symbols(self):
        state = copy.deepcopy(self.state)
        state["positions"] = {"BTC-USDT": state["positions"]["BTC/USDT"]}
        with self.assertRaisesRegex(ValueError, "unsupported paper symbol"):
            build_legacy_state_report(state, self.marks)

    def test_open_position_requires_explicit_mark(self):
        with self.assertRaisesRegex(ValueError, "missing mark price"):
            build_legacy_state_report(self.state, {})

    def test_rejects_non_finite_and_negative_values(self):
        bad = copy.deepcopy(self.state)
        bad["cash_usdt"] = "NaN"
        with self.assertRaisesRegex(ValueError, "finite"):
            build_legacy_state_report(bad, self.marks)
        bad = copy.deepcopy(self.state)
        bad["positions"]["BTC/USDT"]["quantity"] = "-1"
        with self.assertRaisesRegex(ValueError, "positive"):
            build_legacy_state_report(bad, self.marks)

    def test_export_only_reads_state_and_outputs_dashboard_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "paper_state.json"
            marks_path = root / "marks.json"
            state_path.write_text(json.dumps(self.state), encoding="utf-8")
            marks_path.write_text(json.dumps(self.marks), encoding="utf-8")
            before_state = state_path.read_bytes()
            before_marks = marks_path.read_bytes()
            payload = json.loads(export_state_json(
                state_path, marks_path,
                captured_at="2026-11-14T10:00:00-06:00",
                snapshot_id="legacy-test-001",
            ))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["schema_version"], 1)
            self.assertEqual(payload[0]["snapshot_id"], "legacy-test-001")
            self.assertEqual(payload[0]["report"]["equity_usdt"], "960.000")
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertEqual(marks_path.read_bytes(), before_marks)

    def test_refuses_wrong_input_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "other.json"
            wrong.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "paper_state.json"):
                export_state_json(wrong)

    def test_cli_writes_only_json_to_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "paper_state.json"
            marks_path = root / "marks.json"
            state_path.write_text(json.dumps(self.state), encoding="utf-8")
            marks_path.write_text(json.dumps(self.marks), encoding="utf-8")
            import io
            stdout, stderr = io.StringIO(), io.StringIO()
            result = main(["--input", str(state_path), "--marks", str(marks_path)], stdout, stderr)
            self.assertEqual(result, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(len(json.loads(stdout.getvalue())), 1)

    def test_missing_marks_or_bad_json_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "paper_state.json"
            state_path.write_text(json.dumps(self.state), encoding="utf-8")
            with self.assertRaises(ValueError):
                export_state_json(state_path)
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), self.state)


if __name__ == "__main__":
    unittest.main()
