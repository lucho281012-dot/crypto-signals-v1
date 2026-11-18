"""Portfolio backtest for Crypto Signals V2.

Research only: reads local OHLCV archives and writes a separate report.
Never places orders or reads/writes paper_state.json.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from strategy_v2 import (
    FEE_RATE, INTERVAL_MS, MAX_GROSS_EXPOSURE, MAX_OPEN_POSITIONS,
    RISK_FRACTION, STOP_ATR_MULTIPLIER, REWARD_RISK,
    calculate_indicators, latest_completed_row, resample_ohlcv,
)

SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
INITIAL_CASH = 100.0
SLIPPAGE_BPS = 5.0
REPORT_PATH = Path("strategy_v2_backtest_report.json")


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                rows.append({key: item[key] for key in
                             ("timestamp", "open", "high", "low", "close", "volume")})
    if not rows:
        raise ValueError(f"No candles in {path}")
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="raise").astype("int64")
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return frame


def prepare_symbol(symbol: str, root: Path = Path("data/market_history")) -> dict:
    stem = symbol.replace("/", "_")
    five = load_jsonl(root / f"{stem}_5m.jsonl")
    fifteen = load_jsonl(root / f"{stem}_15m.jsonl")
    five = calculate_indicators(five)
    fifteen = calculate_indicators(fifteen)
    one_hour = calculate_indicators(resample_ohlcv(fifteen, "1h"))
    four_hour = calculate_indicators(resample_ohlcv(fifteen, "4h"))
    return {"5m": five, "15m": fifteen, "1h": one_hour, "4h": four_hour}


def signal_at(data: dict, index: int) -> dict | None:
    five = data["5m"]
    current = five.iloc[index]
    needed = ["ema20", "ema50", "ema200", "rsi", "macd", "macd_signal",
              "volume_sma20", "atr", "adx", "atr_percent"]
    if current[needed].isna().any():
        return None
    higher = {
        tf: latest_completed_row(data[tf], int(current["timestamp"]), tf)
        for tf in ("15m", "1h", "4h")
    }
    if any(row is None for row in higher.values()):
        return None
    requirements = {
        "15m": ["ema20", "ema50", "adx"],
        "1h": ["ema50", "ema200", "adx"],
        "4h": ["ema20", "ema50", "adx"],
    }
    if any(higher[tf][fields].isna().any() for tf, fields in requirements.items()):
        return None
    if not (
        higher["4h"]["ema20"] > higher["4h"]["ema50"]
        and higher["1h"]["ema50"] > higher["1h"]["ema200"]
        and higher["15m"]["ema20"] > higher["15m"]["ema50"]
    ):
        return None
    if min(float(higher[tf]["adx"]) for tf in ("1h", "4h")) < 18:
        return None
    if not 0.001 <= float(current["atr_percent"]) <= 0.025:
        return None
    conditions = [
        current["ema20"] > current["ema50"],
        current["close"] > current["ema20"],
        52 <= current["rsi"] <= 70,
        current["macd"] > current["macd_signal"],
        current["volume"] > current["volume_sma20"],
    ]
    if sum(bool(value) for value in conditions) < 4 or float(current["atr"]) <= 0:
        return None
    entry_reference = float(current["close"])
    stop = entry_reference - STOP_ATR_MULTIPLIER * float(current["atr"])
    if stop <= 0 or stop >= entry_reference:
        return None
    return {
        "signal_timestamp": int(current["timestamp"]),
        "entry_reference": entry_reference,
        "atr": float(current["atr"]),
        "stop_distance": STOP_ATR_MULTIPLIER * float(current["atr"]),
        "conditions_passed": sum(bool(value) for value in conditions),
    }


def _mark_equity(cash: float, positions: dict, prices: dict) -> float:
    return cash + sum(pos["quantity"] * prices.get(sym, pos["entry"]) for sym, pos in positions.items())


def _close_position(symbol: str, pos: dict, price: float, timestamp: int, reason: str) -> dict:
    exit_price = price * (1 - SLIPPAGE_BPS / 10_000)
    exit_fee = pos["quantity"] * exit_price * FEE_RATE
    proceeds = pos["quantity"] * exit_price - exit_fee
    pnl = proceeds - pos["entry_cost"]
    return {
        "symbol": symbol, "entry_timestamp": pos["entry_timestamp"],
        "exit_timestamp": int(timestamp), "entry_price": pos["entry"],
        "exit_price": exit_price, "quantity": pos["quantity"],
        "stop": pos["stop"], "target": pos["target"],
        "entry_fee": pos["entry_fee"], "exit_fee": exit_fee,
        "net_pnl": pnl, "reason": reason,
    }


def run_backtest(data_by_symbol: dict, initial_cash: float = INITIAL_CASH,
                 fee_rate: float = FEE_RATE, slippage_bps: float = SLIPPAGE_BPS) -> dict:
    """Simulate one shared cash account, one position per symbol, max 3 positions.

    Risk budget is portfolio-wide: aggregate stop risk including round-trip fees
    cannot exceed 1% of current marked equity. Signals execute at next 5m open.
    If stop and target are both touched in a candle, stop wins. Gaps fill at open.
    """
    global SLIPPAGE_BPS
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial_cash must be a positive finite number")
    if not 0 <= fee_rate < 0.1 or not 0 <= slippage_bps < 1000:
        raise ValueError("Invalid fee or slippage")
    original_slippage = SLIPPAGE_BPS
    SLIPPAGE_BPS = slippage_bps
    cash = float(initial_cash)
    positions = {}
    latest_prices = {}
    trades = []
    equity_curve = []
    signal_queue = {}
    events = []
    try:
        for symbol, data in data_by_symbol.items():
            frame = data["5m"]
            for index in range(200, len(frame)):
                ts = int(frame.iloc[index]["timestamp"])
                events.append((ts, symbol, index))
        events.sort(key=lambda item: (item[0], item[1]))

        cursor = 0
        while cursor < len(events):
            timestamp = events[cursor][0]
            batch = []
            while cursor < len(events) and events[cursor][0] == timestamp:
                batch.append(events[cursor])
                cursor += 1

            # First mark prices and resolve exits for positions already open.
            for _, symbol, index in batch:
                candle = data_by_symbol[symbol]["5m"].iloc[index]
                latest_prices[symbol] = float(candle["open"])
                pos = positions.get(symbol)
                if pos is None:
                    continue
                low, high, open_price = float(candle["low"]), float(candle["high"]), float(candle["open"])
                if low <= pos["stop"]:
                    raw_exit = min(open_price, pos["stop"])
                    trade = _close_position(symbol, pos, raw_exit, timestamp, "stop_loss")
                elif high >= pos["target"]:
                    raw_exit = max(open_price, pos["target"])
                    trade = _close_position(symbol, pos, raw_exit, timestamp, "take_profit")
                else:
                    continue
                trades.append(trade)
                cash += pos["quantity"] * trade["exit_price"] - trade["exit_fee"]
                del positions[symbol]

            # Signals from the immediately preceding closed 5m candle enter now.
            for _, symbol, index in batch:
                data = data_by_symbol[symbol]
                frame = data["5m"]
                if index <= 200 or symbol in positions:
                    continue
                previous_signal = signal_at(data, index - 1)
                if previous_signal is None:
                    continue
                candle = frame.iloc[index]
                raw_entry = float(candle["open"])
                entry = raw_entry * (1 + slippage_bps / 10_000)
                stop = entry - previous_signal["stop_distance"]
                if stop <= 0 or stop >= entry or len(positions) >= MAX_OPEN_POSITIONS:
                    continue
                equity = _mark_equity(cash, positions, latest_prices)
                gross_exposure = sum(
                    p["quantity"] * latest_prices.get(sym, p["entry"])
                    for sym, p in positions.items()
                )
                open_risk = sum(p["risk_budget"] for p in positions.values())
                remaining_risk = max(0.0, equity * RISK_FRACTION - open_risk)
                remaining_exposure = max(0.0, equity * MAX_GROSS_EXPOSURE - gross_exposure)
                risk_per_unit = entry - stop + entry * fee_rate + stop * fee_rate
                if risk_per_unit <= 0 or remaining_risk <= 0:
                    continue
                quantity = min(
                    remaining_risk / risk_per_unit,
                    cash / (entry * (1 + fee_rate)),
                    remaining_exposure / (entry * (1 + fee_rate)),
                )
                if quantity <= 0:
                    continue
                notional = quantity * entry
                entry_fee = notional * fee_rate
                total_debit = notional + entry_fee
                if total_debit > cash + 1e-9:
                    continue
                target = entry + REWARD_RISK * (entry - stop)
                risk_budget = quantity * risk_per_unit
                cash -= total_debit
                positions[symbol] = {
                    "entry": entry, "entry_timestamp": timestamp,
                    "stop": stop, "target": target, "quantity": quantity,
                    "entry_fee": entry_fee, "entry_cost": total_debit,
                    "risk_budget": risk_budget,
                }
                latest_prices[symbol] = entry

            # Close-to-close equity snapshot after all same-timestamp decisions.
            for _, symbol, index in batch:
                latest_prices[symbol] = float(data_by_symbol[symbol]["5m"].iloc[index]["close"])
            equity = _mark_equity(cash, positions, latest_prices)
            equity_curve.append({"timestamp": timestamp, "equity": equity})

        # Mark any remaining positions to the last verified close and charge exit fee.
        for symbol, pos in list(positions.items()):
            frame = data_by_symbol[symbol]["5m"]
            last = frame.iloc[-1]
            exit_price = float(last["close"]) * (1 - slippage_bps / 10_000)
            trade = _close_position(symbol, pos, float(last["close"]), int(last["timestamp"]), "end_of_sample")
            trades.append(trade)
            cash += pos["quantity"] * exit_price - trade["exit_fee"]
            del positions[symbol]

        wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
        losses = [-t["net_pnl"] for t in trades if t["net_pnl"] < 0]
        gross_profit, gross_loss = sum(wins), sum(losses)
        peak = float(initial_cash)
        max_drawdown = 0.0
        for point in equity_curve:
            peak = max(peak, point["equity"])
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - point["equity"]) / peak)
        net_pnl = cash - initial_cash
        return {
            "initial_cash": initial_cash, "final_cash": cash,
            "net_pnl": net_pnl, "return_percent": net_pnl / initial_cash * 100,
            "closed_trades": len(trades), "wins": len(wins), "losses": len(losses),
            "win_rate_percent": len(wins) / len(trades) * 100 if trades else None,
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "expectancy_per_trade": net_pnl / len(trades) if trades else None,
            "max_drawdown_percent": max_drawdown * 100,
            "fees_total": sum(t["entry_fee"] + t["exit_fee"] for t in trades),
            "slippage_bps_per_side": slippage_bps, "fee_rate_per_side": fee_rate,
            "trade_log": trades, "equity_curve": equity_curve,
            "assumptions": {
                "signals_execute_next_5m_open": True,
                "stop_wins_if_stop_and_target_same_candle": True,
                "gap_fill_at_open": True,
                "portfolio_wide_open_risk_cap_percent": RISK_FRACTION * 100,
                "gross_exposure_cap_percent": MAX_GROSS_EXPOSURE * 100,
                "max_open_positions": MAX_OPEN_POSITIONS,
                "no_short_positions": True,
            },
        }
    finally:
        SLIPPAGE_BPS = original_slippage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/market_history")
    parser.add_argument("--output", default=str(REPORT_PATH))
    parser.add_argument("--initial-cash", type=float, default=INITIAL_CASH)
    parser.add_argument("--fee-rate", type=float, default=FEE_RATE)
    parser.add_argument("--slippage-bps", type=float, default=SLIPPAGE_BPS)
    args = parser.parse_args()
    data = {symbol: prepare_symbol(symbol, Path(args.data_dir)) for symbol in SYMBOLS}
    report = {
        "mode": "research_only_no_orders_no_paper_state_changes",
        "symbols": list(SYMBOLS),
        "data": {
            symbol: {
                tf: {
                    "rows": len(frame),
                    "first_timestamp": int(frame.iloc[0]["timestamp"]),
                    "last_timestamp": int(frame.iloc[-1]["timestamp"]),
                }
                for tf, frame in frames.items()
            }
            for symbol, frames in data.items()
        },
        "results": run_backtest(
            data, initial_cash=args.initial_cash,
            fee_rate=args.fee_rate, slippage_bps=args.slippage_bps,
        ),
    }
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {key: value for key, value in report["results"].items()
               if key not in ("trade_log", "equity_curve")}
    print(json.dumps({"data": report["data"], "results": summary,
                      "report_file": args.output}, indent=2))


if __name__ == "__main__":
    main()
