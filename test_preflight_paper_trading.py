import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from preflight_paper_trading import run_preflight, validate_candles


def candles(timeframe_ms, now_ms, count=205):
    start = now_ms - count * timeframe_ms
    return [
        {"timestamp": start + i * timeframe_ms, "open": 100.0, "high": 102.0,
         "low": 99.0, "close": 101.0, "volume": 10.0}
        for i in range(count)
    ]


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 16, 30, tzinfo=timezone.utc)
        self.now_ms = int(self.now.timestamp() * 1000)
        self.market = {
            symbol: {
                "price": 101.0,
                "candles_5m": candles(300_000, self.now_ms),
                "candles_15m": candles(900_000, self.now_ms),
            }
            for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT")
        }

    def write_state(self, directory, positions=None):
        path = Path(directory) / "paper_state.json"
        path.write_text(json.dumps({
            "cash_usdt": 99.5, "positions": positions or {}, "history": [],
            "last_processed_candle": {s: "0" for s in self.market}
        }), encoding="utf-8")
        return path

    def test_read_only_preflight_preserves_state_and_reports_symbols(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_state(directory)
            before = path.read_bytes()
            report = run_preflight(lambda: self.market, lambda *_: None, path, self.now)
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(report["state_file_unchanged"])
            self.assertEqual(set(report["symbols"]), set(self.market))
            self.assertTrue(all(x["signal"] is None for x in report["symbols"].values()))

    def test_stops_if_open_positions_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_state(directory, {"BTC/USDT": {"entry_price": 100}})
            with self.assertRaisesRegex(ValueError, "posiciones abiertas"):
                run_preflight(lambda: self.market, lambda *_: None, path, self.now)

    def test_stops_if_symbol_data_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_state(directory)
            market = dict(self.market)
            market.pop("ETH/USDT")
            with self.assertRaisesRegex(ValueError, "ETH/USDT"):
                run_preflight(lambda: market, lambda *_: None, path, self.now)

    def test_rejects_stale_or_misaligned_candles(self):
        old = candles(300_000, self.now_ms)
        old[-2]["timestamp"] -= 60_000
        with self.assertRaisesRegex(ValueError, "no alineado"):
            validate_candles(old, "5m", self.now)

    def test_rejects_insufficient_history(self):
        with self.assertRaisesRegex(ValueError, "200"):
            validate_candles(candles(300_000, self.now_ms, count=20), "5m", self.now)


if __name__ == "__main__":
    unittest.main()
