
import json

from data_feed import download_candles, ema, rsi, atr
from signal_rules import evaluate_signal


def main():
    candles = download_candles()

    closes = [float(candle[4]) for candle in candles]

    data = {
        "close": closes[-1],
        "ema_50": ema(closes, 50),
        "rsi_14": rsi(closes, 14),
        "atr_14": atr(candles, 14)
    }

    result = evaluate_signal(data)

    result["source"] = "Binance Public Market Data"
    result["symbol"] = "BTCUSDT"
    result["timeframe"] = "H1"
    result["candle_open_utc"] = candles[-1][0]

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({
            "status": "error",
            "message": str(error)
        }, indent=2))
