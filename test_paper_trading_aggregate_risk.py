import unittest
from unittest.mock import patch
from paper_trading import open_position, open_positions, close_position


def fresh(cash=100.0):
    return {"initial_balance": 100.0, "cash_usdt": cash, "positions": {}, "history": []}


class AggregateRiskExposureTests(unittest.TestCase):
    def test_single_signal_capped_at_one_percent(self):
        s = fresh()
        with patch("paper_trading.save_state"):
            ok, _ = open_position(s, "BTC", 10, 9)
        self.assertTrue(ok)
        self.assertAlmostEqual(s["positions"]["BTC"]["risk_budget"], 1.0)

    def test_two_simultaneous_signals_share_budget(self):
        s = fresh()
        with patch("paper_trading.save_state"):
            out = open_positions(s, [
                {"symbol": "BTC", "entry_price": 10, "stop_price": 9},
                {"symbol": "ETH", "entry_price": 10, "stop_price": 9}])
        self.assertTrue(all(x[0] for x in out))
        self.assertAlmostEqual(s["positions"]["BTC"]["risk_budget_target"], .5)
        self.assertAlmostEqual(s["positions"]["ETH"]["risk_budget_target"], .5)
        self.assertAlmostEqual(sum(x["risk_budget"] for x in s["positions"].values()), 1)

    def test_three_requests_are_proportional(self):
        s = fresh()
        req = [{"symbol": sym, "entry_price": 10, "stop_price": 9.95, "risk_demand_usdt": d}
               for sym, d in (("BTC", 1), ("ETH", 2), ("SOL", 3))]
        with patch("paper_trading.save_state"):
            open_positions(s, req)
        self.assertAlmostEqual(s["positions"]["BTC"]["risk_budget_target"], 1/6)
        self.assertAlmostEqual(s["positions"]["ETH"]["risk_budget_target"], 2/6)
        self.assertAlmostEqual(s["positions"]["SOL"]["risk_budget_target"], 3/6)
        self.assertLessEqual(sum(x["risk_budget"] for x in s["positions"].values()), 1 + 1e-9)

    def test_existing_open_risk_is_subtracted(self):
        s = fresh(90)
        q = .4 / 5.195
        s["positions"]["OLD"] = {"quantity": q, "entry_price": 100, "stop_price": 95,
                                 "entry_fee": q * 100 * .001}
        with patch("paper_trading.save_state"):
            open_positions(s, [{"symbol": "NEW", "entry_price": 10, "stop_price": 9}])
        risk = sum(p["quantity"] * (p["entry_price"] - p["stop_price"])
                   + p["entry_fee"] + p["quantity"] * p["stop_price"] * .001
                   for p in s["positions"].values())
        self.assertAlmostEqual(risk, 1, places=8)

    def test_exhausted_risk_blocks_new_position(self):
        s = fresh(90)
        q = 1 / 5.195
        s["positions"]["OLD"] = {"quantity": q, "entry_price": 100, "stop_price": 95,
                                 "entry_fee": q * 100 * .001}
        with patch("paper_trading.save_state"):
            out = open_positions(s, [{"symbol": "NEW", "entry_price": 10, "stop_price": 9}])
        self.assertFalse(out[0][0])
        self.assertNotIn("NEW", s["positions"])

    def test_close_releases_risk_and_exposure(self):
        s = fresh()
        with patch("paper_trading.save_state"):
            self.assertTrue(open_positions(s, [{"symbol": "BTC", "entry_price": 10, "stop_price": 9}])[0][0])
            self.assertTrue(close_position(s, "BTC", 10)[0])
            self.assertTrue(open_positions(s, [{"symbol": "ETH", "entry_price": 10, "stop_price": 9}])[0][0])

    def test_entry_fee_is_in_global_exposure(self):
        s = fresh()
        q = 94.99 / 10.01
        s["positions"]["OLD"] = {"quantity": q, "entry_price": 10, "stop_price": 9.95,
                                 "entry_fee": q * 10 * .001}
        with patch("paper_trading.save_state"):
            out = open_positions(s, [{"symbol": "NEW", "entry_price": 10, "stop_price": 9}])
        exposure = sum(p["quantity"] * p["entry_price"] + p["entry_fee"]
                       for p in s["positions"].values())
        self.assertLessEqual(exposure, 95 + 1e-8)
        self.assertTrue(out[0][0])

    def test_at_exposure_cap_new_position_rejected(self):
        s = fresh()
        q = 95 / 10.01
        s["positions"]["OLD"] = {"quantity": q, "entry_price": 10, "stop_price": 9.95,
                                 "entry_fee": q * 10 * .001}
        with patch("paper_trading.save_state"):
            out = open_positions(s, [{"symbol": "NEW", "entry_price": 10, "stop_price": 9}])
        self.assertFalse(out[0][0])

    def test_cash_cap_includes_entry_fee(self):
        s = fresh(2)
        with patch("paper_trading.save_state"):
            out = open_positions(s, [{"symbol": "BTC", "entry_price": 10, "stop_price": 9}])
        self.assertTrue(out[0][0])
        p = s["positions"]["BTC"]
        self.assertLessEqual(p["quantity"] * p["entry_price"] + p["entry_fee"], 2 + 1e-9)
        self.assertLessEqual(p["risk_budget"], .205)

    def test_invalid_request_does_not_mutate_state(self):
        s = fresh()
        before = repr(s)
        with patch("paper_trading.save_state"), self.assertRaises(ValueError):
            open_positions(s, [{"symbol": "BTC", "entry_price": 10, "stop_price": 10}])
        self.assertEqual(repr(s), before)

    def test_duplicate_batch_symbols_rejected_atomically(self):
        s = fresh()
        before = repr(s)
        with patch("paper_trading.save_state"), self.assertRaises(ValueError):
            open_positions(s, [
                {"symbol": "BTC", "entry_price": 10, "stop_price": 9},
                {"symbol": "BTC", "entry_price": 10, "stop_price": 9}])
        self.assertEqual(repr(s), before)

    def test_malformed_existing_position_blocks_new_entries(self):
        s = fresh()
        s["positions"]["OLD"] = {"quantity": 1, "entry_price": 10}
        with patch("paper_trading.save_state"), self.assertRaises(KeyError):
            open_positions(s, [{"symbol": "NEW", "entry_price": 10, "stop_price": 9}])
        self.assertNotIn("NEW", s["positions"])

    def test_non_finite_prices_rejected(self):
        for price in (float("nan"), float("inf"), -1):
            s = fresh()
            with patch("paper_trading.save_state"), self.assertRaises(ValueError):
                open_positions(s, [{"symbol": "BTC", "entry_price": price, "stop_price": 9}])
            self.assertEqual(s["positions"], {})

    def test_existing_exposure_above_cap_blocks_new_entries_without_worsening(self):
        s = fresh()
        q = 95.01 / 10.01
        s["positions"]["LEGACY"] = {"quantity": q, "entry_price": 10, "stop_price": 9.95,
                                    "entry_fee": q * 10 * .001}
        before = sum(x["quantity"] * x["entry_price"] + x["entry_fee"]
                     for x in s["positions"].values())
        with patch("paper_trading.save_state"):
            out = open_positions(s, [{"symbol": "NEW", "entry_price": 10, "stop_price": 9}])
        after = sum(x["quantity"] * x["entry_price"] + x["entry_fee"]
                    for x in s["positions"].values())
        self.assertFalse(out[0][0])
        self.assertAlmostEqual(after, before)
        self.assertNotIn("NEW", s["positions"])

    def test_existing_risk_above_cap_blocks_new_entries_without_worsening(self):
        s = fresh()
        q = 1.01 / (0.05 + 10 * .001 + 9.95 * .001)
        s["positions"]["LEGACY"] = {"quantity": q, "entry_price": 10, "stop_price": 9.95,
                                    "entry_fee": q * 10 * .001}
        before = sum(pt["quantity"] * (pt["entry_price"] - pt["stop_price"])
                     + pt["entry_fee"] + pt["quantity"] * pt["stop_price"] * .001
                     for pt in s["positions"].values())
        with patch("paper_trading.save_state"):
            out = open_positions(s, [{"symbol": "NEW", "entry_price": 10, "stop_price": 9}])
        after = sum(pt["quantity"] * (pt["entry_price"] - pt["stop_price"])
                    + pt["entry_fee"] + pt["quantity"] * pt["stop_price"] * .001
                    for pt in s["positions"].values())
        self.assertFalse(out[0][0])
        self.assertAlmostEqual(after, before)
        self.assertNotIn("NEW", s["positions"])

    def test_batch_rejection_is_atomic_when_one_request_is_invalid(self):
        s = fresh()
        before = repr(s)
        with patch("paper_trading.save_state"), self.assertRaises(ValueError):
            open_positions(s, [
                {"symbol": "BTC", "entry_price": 10, "stop_price": 9},
                {"symbol": "ETH", "entry_price": 10, "stop_price": 10}])
        self.assertEqual(repr(s), before)

    def test_nonpositive_risk_demand_is_rejected(self):
        s = fresh()
        with patch("paper_trading.save_state"), self.assertRaises(ValueError):
            open_positions(s, [{"symbol": "BTC", "entry_price": 10, "stop_price": 9,
                                "risk_demand_usdt": 0}])
        self.assertEqual(s["positions"], {})

    def test_entry_fee_included_for_every_existing_position(self):
        s = fresh()
        s["positions"]["A"] = {"quantity": 1, "entry_price": 10, "stop_price": 9.95,
                               "entry_fee": .01}
        s["positions"]["B"] = {"quantity": 2, "entry_price": 10, "stop_price": 9.95,
                               "entry_fee": .02}
        committed = 30.03
        with patch("paper_trading.save_state"):
            out = open_positions(s, [{"symbol": "C", "entry_price": 10, "stop_price": 9}])
        after = sum(x["quantity"] * x["entry_price"] + x["entry_fee"]
                    for x in s["positions"].values())
        self.assertTrue(out[0][0])
        self.assertAlmostEqual(after, committed + s["positions"]["C"]["quantity"] * 10.01)
        self.assertLessEqual(after, 95 + 1e-8)

    def test_target_price_is_preserved_for_batch_entry(self):
        s = fresh()
        with patch("paper_trading.save_state"):
            open_positions(s, [{"symbol": "BTC", "entry_price": 10, "stop_price": 9,
                                 "target_price": 12}])
        self.assertEqual(s["positions"]["BTC"]["target_price"], 12)

    def test_single_open_position_cannot_spend_more_than_remaining_risk(self):
        s = fresh()
        q = .6 / 5.195
        s["positions"]["OLD"] = {"quantity": q, "entry_price": 100, "stop_price": 95,
                                 "entry_fee": q * 100 * .001}
        s["cash_usdt"] = 90
        with patch("paper_trading.save_state"):
            ok, _ = open_position(s, "NEW", 10, 9)
        self.assertTrue(ok)
        total = sum(pt["quantity"] * (pt["entry_price"] - pt["stop_price"])
                    + pt["entry_fee"] + pt["quantity"] * pt["stop_price"] * .001
                    for pt in s["positions"].values())
        self.assertLessEqual(total, 1 + 1e-8)


if __name__ == "__main__":
    unittest.main()
