"""Research-only portfolio backtester for Crypto Signals V2."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from strategy_v2 import (
    FEE_RATE, INTERVAL_MS, MAX_GROSS_EXPOSURE, MAX_OPEN_POSITIONS,
    RISK_FRACTION, REWARD_RISK, STOP_ATR_MULTIPLIER,
    calculate_indicators, evaluate_buy_signal_at, resample_ohlcv,
)

SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
INITIAL_CASH = 100.0
SLIPPAGE_BPS = 5.0


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows.append({key: row[key] for key in
                             ("timestamp", "open", "high", "low", "close", "volume")})
    if not rows:
        raise ValueError(f"No candles in {path}")
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="raise").astype("int64")
    return frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def prepare_symbol(symbol: str, root: Path = Path("data/market_history")) -> dict:
    stem = symbol.replace("/", "_")
    five = calculate_indicators(load_jsonl(root / f"{stem}_5m.jsonl"))
    fifteen_raw = load_jsonl(root / f"{stem}_15m.jsonl")
    fifteen = calculate_indicators(fifteen_raw)
    one_hour = calculate_indicators(resample_ohlcv(fifteen_raw, "1h"))
    four_hour = calculate_indicators(resample_ohlcv(fifteen_raw, "4h"))
    return {"5m": five, "15m": fifteen, "1h": one_hour, "4h": four_hour}


def signal_at(data: dict, index: int) -> dict | None:
    """Adapt the shared V2 signal result to the backtest's stop-distance input."""
    setup = evaluate_buy_signal_at(data, index)
    if setup is None:
        return None
    return {
        "stop_distance": float(setup["entry_reference"]) - float(setup["stop"]),
        "signal_timestamp": int(setup["timestamp"]),
    }

def _equity(cash: float, positions: dict, marks: dict) -> float:
    return cash + sum(p["quantity"] * marks.get(s, p["entry"])
                      for s, p in positions.items())


def _close_trade(symbol: str, pos: dict, raw_price: float, timestamp: int,
                 reason: str, fee_rate: float, slippage_bps: float) -> dict:
    price = raw_price * (1 - slippage_bps / 10_000)
    exit_fee = pos["quantity"] * price * fee_rate
    proceeds = pos["quantity"] * price - exit_fee
    return {
        "symbol": symbol, "entry_timestamp": pos["entry_timestamp"],
        "exit_timestamp": int(timestamp), "entry_price": pos["entry"],
        "exit_price": price, "quantity": pos["quantity"],
        "stop": pos["stop"], "target": pos["target"],
        "entry_fee": pos["entry_fee"], "exit_fee": exit_fee,
        "net_pnl": proceeds - pos["entry_cost"], "reason": reason,
    }


def run_backtest(data_by_symbol: dict, initial_cash: float = INITIAL_CASH,
                 fee_rate: float = FEE_RATE, slippage_bps: float = SLIPPAGE_BPS) -> dict:
    """Single shared portfolio; aggregate open stop risk capped at 1% equity.

    Signal on a closed candle enters at the next contiguous 5m candle open.
    Existing positions exit before new entries at each timestamp. If stop and
    target both touch in one candle, stop wins. Gap exits fill at candle open.
    """
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial_cash must be positive and finite")
    if not math.isfinite(fee_rate) or not 0 <= fee_rate < 0.1:
        raise ValueError("fee_rate must be finite and in [0, 0.1)")
    if not math.isfinite(slippage_bps) or not 0 <= slippage_bps < 1000:
        raise ValueError("slippage_bps must be finite and in [0, 1000)")
    events = []
    for symbol, data in data_by_symbol.items():
        frame = data["5m"]
        for i in range(200, len(frame)):
            events.append((int(frame.iloc[i]["timestamp"]), symbol, i))
    events.sort(key=lambda item: (item[0], item[1]))

    cash = float(initial_cash)
    positions, marks, trades, curve = {}, {}, [], []
    cursor = 0
    while cursor < len(events):
        timestamp = events[cursor][0]
        batch = []
        while cursor < len(events) and events[cursor][0] == timestamp:
            batch.append(events[cursor])
            cursor += 1

        # Update open prices and process exits before considering new entries.
        for _, symbol, index in batch:
            candle = data_by_symbol[symbol]["5m"].iloc[index]
            marks[symbol] = float(candle["open"])
            pos = positions.get(symbol)
            if pos is None:
                continue
            low, high, op = float(candle["low"]), float(candle["high"]), float(candle["open"])
            if low <= pos["stop"]:
                raw, reason = min(op, pos["stop"]), "stop_loss"
            elif high >= pos["target"]:
                raw, reason = max(op, pos["target"]), "take_profit"
            else:
                continue
            trade = _close_trade(symbol, pos, raw, timestamp, reason, fee_rate, slippage_bps)
            trades.append(trade)
            cash += pos["quantity"] * trade["exit_price"] - trade["exit_fee"]
            del positions[symbol]

        # Signals from prior fully closed candles enter at this candle's open.
        for _, symbol, index in batch:
            frame = data_by_symbol[symbol]["5m"]
            if index <= 200 or symbol in positions or len(positions) >= MAX_OPEN_POSITIONS:
                continue
            if int(frame.iloc[index]["timestamp"]) - int(frame.iloc[index - 1]["timestamp"]) != INTERVAL_MS["5m"]:
                continue
            setup = signal_at(data_by_symbol[symbol], index - 1)
            if setup is None:
                continue
            entry = float(frame.iloc[index]["open"]) * (1 + slippage_bps / 10_000)
            stop = entry - setup["stop_distance"]
            if stop <= 0 or stop >= entry:
                continue
            equity = _equity(cash, positions, marks)
            gross = sum(p["quantity"] * marks.get(s, p["entry"])
                        for s, p in positions.items())
            open_risk = sum(p["risk_budget"] for p in positions.values())
            risk_left = max(0.0, equity * RISK_FRACTION - open_risk)
            exposure_left = max(0.0, equity * MAX_GROSS_EXPOSURE - gross)
            risk_per_unit = entry - stop + entry * fee_rate + stop * fee_rate
            if risk_per_unit <= 0 or risk_left <= 0:
                continue
            quantity = min(
                risk_left / risk_per_unit,
                cash / (entry * (1 + fee_rate)),
                exposure_left / (entry * (1 + fee_rate)),
            )
            if quantity <= 0:
                continue
            notional = quantity * entry
            entry_fee = notional * fee_rate
            debit = notional + entry_fee
            if debit > cash + 1e-9:
                continue
            pos = {
                "entry": entry, "entry_timestamp": timestamp,
                "stop": stop, "target": entry + REWARD_RISK * (entry - stop),
                "quantity": quantity, "entry_fee": entry_fee,
                "entry_cost": debit, "risk_budget": quantity * risk_per_unit,
            }
            cash -= debit
            positions[symbol] = pos
            marks[symbol] = entry

        for _, symbol, index in batch:
            marks[symbol] = float(data_by_symbol[symbol]["5m"].iloc[index]["close"])
        curve.append({"timestamp": timestamp, "equity": _equity(cash, positions, marks)})

    # Conservative end-of-sample liquidation, with the same fees and slippage.
    for symbol, pos in list(positions.items()):
        last = data_by_symbol[symbol]["5m"].iloc[-1]
        trade = _close_trade(symbol, pos, float(last["close"]), int(last["timestamp"]),
                             "end_of_sample", fee_rate, slippage_bps)
        trades.append(trade)
        cash += pos["quantity"] * trade["exit_price"] - trade["exit_fee"]
        del positions[symbol]

    wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
    losses = [-t["net_pnl"] for t in trades if t["net_pnl"] < 0]
    peak, max_dd = float(initial_cash), 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        if peak > 0:
            max_dd = max(max_dd, (peak - point["equity"]) / peak)
    net = cash - initial_cash
    return {
        "initial_cash": initial_cash, "final_cash": cash, "net_pnl": net,
        "return_percent": net / initial_cash * 100,
        "closed_trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_percent": len(wins) / len(trades) * 100 if trades else None,
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "expectancy_per_trade": net / len(trades) if trades else None,
        "max_drawdown_percent": max_dd * 100,
        "fees_total": sum(t["entry_fee"] + t["exit_fee"] for t in trades),
        "fee_rate_per_side": fee_rate, "slippage_bps_per_side": slippage_bps,
        "trade_log": trades, "equity_curve": curve,
        "assumptions": {
            "next_contiguous_5m_open_entry": True,
            "stop_priority_when_both_levels_hit": True, "gap_fill_at_open": True,
            "portfolio_open_risk_cap_percent": RISK_FRACTION * 100,
            "gross_exposure_cap_percent": MAX_GROSS_EXPOSURE * 100,
            "max_open_positions": MAX_OPEN_POSITIONS,
            "long_only": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/market_history")
    parser.add_argument("--output", default="strategy_v2_backtest_report.json")
    parser.add_argument("--initial-cash", type=float, default=INITIAL_CASH)
    parser.add_argument("--fee-rate", type=float, default=FEE_RATE)
    parser.add_argument("--slippage-bps", type=float, default=SLIPPAGE_BPS)
    args = parser.parse_args()
    prepared = {s: prepare_symbol(s, Path(args.data_dir)) for s in SYMBOLS}
    metadata = {
        symbol: {
            tf: {"rows": len(frame), "first_timestamp": int(frame.iloc[0]["timestamp"]),
                 "last_timestamp": int(frame.iloc[-1]["timestamp"])}
            for tf, frame in frames.items()
        } for symbol, frames in prepared.items()
    }
    result = run_backtest(prepared, args.initial_cash, args.fee_rate, args.slippage_bps)
    report = {
        "mode": "research_only_no_orders_no_paper_state_changes",
        "symbols": list(SYMBOLS), "data": metadata, "results": result,
    }
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k not in ("trade_log", "equity_curve")}
    print(json.dumps({"data": metadata, "results": summary, "report_file": args.output}, indent=2))


if __name__ == "__main__":
    main()
