import unittest

from paper_execution import simulate_market_order


NOW = 2_000_000_000_000


def sample_book():
    return {
        "symbol": "BTC/USDT",
        "timestamp_ms": NOW - 100,
        "received_at_ms": NOW - 50,
        "checksum_valid": True,
        "bids": [
            ["100.00", "1.0"],
            ["99.00", "2.0"],
            ["98.00", "3.0"],
        ],
        "asks": [
            ["101.00", "0.5"],
            ["102.00", "1.0"],
            ["103.00", "2.0"],
        ],
    }


class PaperExecutionTests(unittest.TestCase):
    def test_buy_consumes_asks_and_calculates_fee_and_slippage(self):
        result = simulate_market_order(sample_book(), "BUY", "0.75", NOW)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["levels_consumed"], 2)
        self.assertAlmostEqual(result["gross_notional_usdt"], 76.0)
        self.assertAlmostEqual(result["average_fill_price"], 76.0 / 0.75)
        self.assertAlmostEqual(result["fee_usdt"], 0.076)
        self.assertGreater(result["slippage_pct"], 0)

    def test_sell_consumes_bids(self):
        result = simulate_market_order(sample_book(), "SELL", "1.5", NOW)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["levels_consumed"], 2)
        self.assertAlmostEqual(result["gross_notional_usdt"], 199.0)
        self.assertAlmostEqual(result["fee_usdt"], 0.199)
        self.assertLess(result["cash_flow_usdt"], result["gross_notional_usdt"])

    def test_buy_within_top_level_has_zero_slippage(self):
        result = simulate_market_order(sample_book(), "BUY", "0.25", NOW)
        self.assertTrue(result["ok"], result)
        self.assertAlmostEqual(result["slippage_pct"], 0.0)
        self.assertEqual(result["levels_consumed"], 1)

    def test_rejects_unverified_checksum(self):
        book = sample_book()
        book["checksum_valid"] = False
        result = simulate_market_order(book, "BUY", "0.1", NOW)
        self.assertFalse(result["ok"])
        self.assertIn("checksum", result["reason"])

    def test_rejects_stale_local_book_event(self):
        book = sample_book()
        book["received_at_ms"] = NOW - 5_000
        result = simulate_market_order(book, "BUY", "0.1", NOW)
        self.assertFalse(result["ok"])
        self.assertIn("stale", result["reason"])

    def test_rejects_stale_exchange_timestamp(self):
        book = sample_book()
        book["timestamp_ms"] = NOW - 20_000
        result = simulate_market_order(book, "BUY", "0.1", NOW)
        self.assertFalse(result["ok"])
        self.assertIn("timestamp is stale", result["reason"])

    def test_rejects_future_timestamp(self):
        book = sample_book()
        book["timestamp_ms"] = NOW + 5_000
        result = simulate_market_order(book, "BUY", "0.1", NOW)
        self.assertFalse(result["ok"])

    def test_rejects_crossed_book(self):
        book = sample_book()
        book["asks"][0][0] = "99.00"
        result = simulate_market_order(book, "BUY", "0.1", NOW)
        self.assertFalse(result["ok"])
        self.assertIn("crossed", result["reason"])

    def test_rejects_insufficient_depth_without_partial_fill(self):
        result = simulate_market_order(sample_book(), "BUY", "10", NOW)
        self.assertFalse(result["ok"])
        self.assertIn("insufficient", result["reason"])
        self.assertNotIn("fills", result)

    def test_rejects_excessive_slippage(self):
        result = simulate_market_order(
            sample_book(), "BUY", "0.75", NOW, max_slippage_pct="0.001"
        )
        self.assertFalse(result["ok"])
        self.assertIn("slippage", result["reason"])

    def test_rejects_bad_side_and_quantity(self):
        self.assertFalse(simulate_market_order(sample_book(), "HOLD", "1", NOW)["ok"])
        self.assertFalse(simulate_market_order(sample_book(), "BUY", "0", NOW)["ok"])
        self.assertFalse(simulate_market_order(sample_book(), "SELL", "-1", NOW)["ok"])

    def test_rejects_unsorted_levels(self):
        book = sample_book()
        book["asks"][0], book["asks"][1] = book["asks"][1], book["asks"][0]
        result = simulate_market_order(book, "BUY", "0.1", NOW)
        self.assertFalse(result["ok"])
        self.assertIn("sorted", result["reason"])

    def test_rejects_more_than_ten_levels(self):
        book = sample_book()
        book["bids"] = [[str(100-i), "1"] for i in range(11)]
        result = simulate_market_order(book, "SELL", "0.1", NOW)
        self.assertFalse(result["ok"])
        self.assertIn("more than 10", result["reason"])

    def test_does_not_mutate_input_book(self):
        book = sample_book()
        before = repr(book)
        simulate_market_order(book, "BUY", "0.75", NOW)
        self.assertEqual(repr(book), before)

    def test_buy_cash_flow_includes_fee(self):
        result = simulate_market_order(sample_book(), "BUY", "0.5", NOW)
        self.assertTrue(result["ok"], result)
        self.assertAlmostEqual(result["cash_flow_usdt"], -50.5505)


if __name__ == "__main__":
    unittest.main()
