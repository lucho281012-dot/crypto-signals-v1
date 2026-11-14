import json
import tempfile
import unittest
from pathlib import Path

from audit_signal_performance import build_report, validate


def make_signal(sid, status="TP2", symbol="BTC/USDT", side="LONG"):
    if side == "LONG":
        entry, stop, tp1, tp2 = 100.0, 90.0, 110.0, 120.0
    else:
        entry, stop, tp1, tp2 = 100.0, 110.0, 90.0, 80.0
    return {
        "id": sid, "symbol": symbol, "side": side,
        "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2,
        "status": status, "signal_candle_ts": 1,
    }


class SignalPerformanceAuditTests(unittest.TestCase):
    def test_tp2_and_sl_are_scored_in_r(self):
        report = build_report([
            make_signal("win", "TP2"),
            make_signal("loss", "SL", side="SHORT"),
        ])
        self.assertEqual(report["total"]["gross_total_r"], 1.0)
        self.assertEqual(report["total"]["gross_expectancy_r"], 0.5)
        self.assertEqual(report["total"]["definite_closed"], 2)

    def test_uncertain_and_active_are_excluded(self):
        report = build_report([
            make_signal("win", "TP2"),
            make_signal("partial", "SL_AFTER_TP1"),
            make_signal("ambiguous", "AMBIGUOUS"),
            make_signal("active", "ACTIVE"),
        ])
        total = report["total"]
        self.assertEqual(total["definite_closed"], 1)
        self.assertEqual(total["gross_total_r"], 2.0)
        self.assertEqual(total["sl_after_tp1"], 1)
        self.assertEqual(total["ambiguous"], 1)
        self.assertEqual(total["active"], 1)
        self.assertEqual(total["sl_after_tp1_scenarios_r"]["half_at_tp1_half_at_break_even"], 0.5)

    def test_fee_is_optional(self):
        gross = build_report([make_signal("win", "TP2")])
        net = build_report([make_signal("win", "TP2")], fee_bps=10)
        self.assertIsNone(gross["total"]["net_total_r"])
        self.assertIsNotNone(net["total"]["net_total_r"])
        self.assertLess(net["total"]["net_total_r"], gross["total"]["gross_total_r"])

    def test_symbol_breakdown(self):
        report = build_report([
            make_signal("btc", "TP2", "BTC/USDT"),
            make_signal("eth", "SL", "ETH/USDT", "SHORT"),
        ])
        self.assertEqual(set(report["by_symbol"]), {"BTC/USDT", "ETH/USDT"})
        self.assertEqual(report["by_symbol"]["ETH/USDT"]["sl"], 1)

    def test_duplicate_and_bad_levels_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicado"):
            validate([make_signal("same"), make_signal("same")])
        broken = make_signal("broken")
        broken["tp2"] = 111
        with self.assertRaisesRegex(ValueError, "TP2"):
            validate([broken])

    def test_source_file_is_not_modified(self):
        records = [make_signal("read-only")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps(records), encoding="utf-8")
            before = path.read_bytes()
            loaded = json.loads(path.read_text(encoding="utf-8"))
            build_report(loaded)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
