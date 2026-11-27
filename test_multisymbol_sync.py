import unittest

from market_data import SYMBOLS, validate_entry_round


def candle(timestamp, price=100.0):
    return {
        "timestamp": timestamp,
        "open": price,
        "high": price + 1,
        "low": price - 1,
        "close": price,
        "volume": 10.0,
    }


def valid_market_data():
    result = {}
    for index, symbol in enumerate(SYMBOLS):
        price = 100.0 + index
        result[symbol] = {
            "candles_5m": [
                candle(300000, price),
                candle(600000, price),
                candle(900000, price + 0.5),
            ],
            "candles_15m": [
                candle(0, price),
                candle(900000, price),
            ],
        }
    return result


class MultiSymbolEntrySynchronizationTests(unittest.TestCase):

    def test_accepts_three_symbols_with_same_closed_5m_timestamp(self):
        result = validate_entry_round(valid_market_data())

        self.assertEqual(set(result), set(SYMBOLS))
        for metadata in result.values():
            self.assertEqual(metadata["signal_timestamp"], 600000)
            self.assertEqual(metadata["entry_timestamp"], 900000)
            self.assertEqual(metadata["entry_price"], 100.5)

    def test_rejects_missing_symbol_before_any_entry_can_be_authorized(self):
        data = valid_market_data()
        del data[SYMBOLS[-1]]

        with self.assertRaisesRegex(ValueError, "faltan símbolos"):
            validate_entry_round(data)

    def test_rejects_different_latest_closed_5m_timestamps(self):
        data = valid_market_data()
        data[SYMBOLS[1]]["candles_5m"] = [
            candle(600000),
            candle(900000),
            candle(1200000),
        ]

        with self.assertRaisesRegex(ValueError, "no comparten el mismo timestamp"):
            validate_entry_round(data)

    def test_rejects_unsorted_or_duplicate_5m_candles(self):
        data = valid_market_data()
        data[SYMBOLS[0]]["candles_5m"][1:] = [
            candle(900000),
            candle(900000),
        ]

        with self.assertRaisesRegex(ValueError, "desordenadas o duplicadas"):
            validate_entry_round(data)

    def test_rejects_entry_candle_that_is_not_immediately_after_signal(self):
        data = valid_market_data()
        data[SYMBOLS[0]]["candles_5m"][-1] = candle(1200000)

        with self.assertRaisesRegex(ValueError, "inmediatamente posterior"):
            validate_entry_round(data)

    def test_rejects_missing_next_5m_candle_after_no_trade_gap(self):
        data = valid_market_data()
        data[SYMBOLS[0]]["candles_5m"][-1] = candle(1200000)

        with self.assertRaisesRegex(ValueError, "inmediatamente posterior"):
            validate_entry_round(data)

    def test_rejects_unaligned_5m_timestamp(self):
        data = valid_market_data()
        data[SYMBOLS[0]]["candles_5m"][1] = candle(610000)

        with self.assertRaisesRegex(ValueError, "desalineado"):
            validate_entry_round(data)

    def test_rejects_stale_or_misaligned_15m_trend_candle(self):
        data = valid_market_data()
        data[SYMBOLS[0]]["candles_15m"] = [
            candle(900000),
            candle(1800000),
        ]

        with self.assertRaisesRegex(ValueError, "última vela 15m cerrada"):
            validate_entry_round(data)

    def test_rejects_15m_candles_out_of_order(self):
        data = valid_market_data()
        data[SYMBOLS[0]]["candles_15m"] = [
            candle(900000),
            candle(0),
        ]

        with self.assertRaisesRegex(ValueError, "desordenadas o duplicadas"):
            validate_entry_round(data)

    def test_result_is_independent_of_market_data_dictionary_order(self):
        data = valid_market_data()
        reversed_data = dict(reversed(list(data.items())))

        self.assertEqual(
            validate_entry_round(data),
            validate_entry_round(reversed_data),
        )


if __name__ == "__main__":
    unittest.main()
