import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import market_history_collector as collector


class FakeExchange:
    rateLimit = 0
    def __init__(self, rows, now):
        self.rows = rows
        self.now = now
        self.calls = []
    def fetch_ohlcv(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return self.rows
    def milliseconds(self):
        return self.now


class MarketHistoryCollectorTests(unittest.TestCase):
    def test_only_closed_candles_are_returned(self):
        exchange = FakeExchange([
            [0, 10, 11, 9, 10, 5],
            [300000, 10, 12, 9, 11, 6],
        ], now=600000)
        result = collector.fetch_closed_candles(exchange, "BTC/USDT", "5m")
        self.assertEqual([c["timestamp"] for c in result], [0, 300000])

    def test_archive_deduplicates_and_appends_new_candles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "BTC_USDT_5m.jsonl"
            path.write_text(json.dumps({
                "timestamp": 0, "open": 10, "high": 11,
                "low": 9, "close": 10, "volume": 1,
            }) + "\n", encoding="utf-8")
            exchange = FakeExchange([
                [0, 10, 12, 9, 11, 2],
                [300000, 11, 12, 10, 12, 3],
            ], now=600000)
            with patch.object(collector, "archive_path", return_value=path):
                result = collector.collect_one(exchange, "BTC/USDT", "5m")
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["close"], 11.0)
            self.assertEqual(result["new_candles"], 1)
            self.assertEqual(exchange.calls[0][1]["since"], 300000)

    def test_empty_archive_seeds_latest_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ETH_USDT_15m.jsonl"
            exchange = FakeExchange([[0, 1, 2, 1, 2, 3]], now=900000)
            with patch.object(collector, "archive_path", return_value=path):
                result = collector.collect_one(exchange, "ETH/USDT", "15m")
            self.assertEqual(result["total_candles"], 1)
            self.assertNotIn("since", exchange.calls[0][1])


if __name__ == "__main__":
    unittest.main()
