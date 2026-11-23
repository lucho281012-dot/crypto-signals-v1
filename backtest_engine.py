"""Cost-aware, deterministic long-only OHLCV backtest execution core.

Signals are generated externally from CLOSED candles. A signal timestamp must
match its source candle; execution occurs at the NEXT candle open. This module
does not fetch data or generate strategy signals.
"""
from math import isfinite


def _validate_candles(candles):
    if len(candles) < 2:
        raise ValueError("Se requieren al menos dos velas")
    previous = None
    for index, candle in enumerate(candles):
        required = ("timestamp", "open", "high", "low", "close", "volume")
        if any(key not in candle for key in required):
            raise ValueError(f"Vela {index}: faltan campos OHLCV")
        timestamp = int(candle["timestamp"])
        values = [float(candle[k]) for k in ("open", "high", "low", "close", "volume")]
        if not all(isfinite(value) for value in values):
            raise ValueError(f"Vela {index}: valores no finitos")
        open_, high, low, close, volume = values
        if min(open_, high, low, close) <= 0 or volume < 0:
            raise ValueError(f"Vela {index}: precio/volumen inválido")
        if high < max(open_, close, low) or low > min(open_, close, high):
            raise ValueError(f"Vela {index}: OHLC inconsistente")
        if previous is not None and timestamp <= previous:
            raise ValueError("Las velas deben tener timestamps únicos y crecientes")
        previous = timestamp


def run_long_backtest(
    candles,
    signals,
    initial_balance=100.0,
    risk_percent=0.01,
    max_exposure_percent=0.95,
    fee_rate=0.001,
    slippage_rate=0.0005,
    stop_atr_multiple=1.2,
    reward_risk=2.0,
):
    """Simulate BUY signals at next-open with fees, adverse slippage and stops.

    Each signal is {"timestamp": closed_candle_timestamp, "side": "BUY",
    "atr": positive_float}. At most one position is open at a time.
    """
    _validate_candles(candles)
    params = (initial_balance, risk_percent, max_exposure_percent, fee_rate,
              slippage_rate, stop_atr_multiple, reward_risk)
    if not all(isfinite(float(x)) for x in params):
        raise ValueError("Parámetros no finitos")
    if initial_balance <= 0 or not 0 < risk_percent <= 1:
        raise ValueError("Balance o riesgo inválido")
    if not 0 < max_exposure_percent <= 1 or not 0 <= fee_rate < 1:
        raise ValueError("Exposición o comisión inválida")
    if not 0 <= slippage_rate < 1 or stop_atr_multiple <= 0 or reward_risk <= 0:
        raise ValueError("Slippage o múltiplos inválidos")

    index_by_timestamp = {int(c["timestamp"]): i for i, c in enumerate(candles)}
    signal_by_index = {}
    for signal in signals:
        timestamp = int(signal["timestamp"])
        if timestamp not in index_by_timestamp:
            raise ValueError(f"Señal sin vela correspondiente: {timestamp}")
        index = index_by_timestamp[timestamp]
        if index >= len(candles) - 1:
            raise ValueError("No existe vela siguiente para ejecutar la señal")
        if signal.get("side") != "BUY":
            raise ValueError("Este motor solo admite señales BUY")
        atr = float(signal["atr"])
        if not isfinite(atr) or atr <= 0:
            raise ValueError("ATR de señal inválido")
        if index in signal_by_index:
            raise ValueError("Señales duplicadas en la misma vela")
        signal_by_index[index] = atr

    cash = float(initial_balance)
    position = None
    trades = []
    equity_curve = []
    peak = float(initial_balance)
    max_drawdown = 0.0

    for i, candle in enumerate(candles):
        open_ = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        # Execute a signal from the previous CLOSED candle at this bar's open.
        if position is None and i > 0 and (i - 1) in signal_by_index:
            atr = signal_by_index[i - 1]
            entry = open_ * (1 + slippage_rate)
            stop_distance = stop_atr_multiple * atr
            stop = entry - stop_distance
            target = entry + reward_risk * stop_distance
            risk_budget = (cash * risk_percent)
            risk_per_unit = (stop_distance + entry * fee_rate
                             + stop * (1 - slippage_rate) * fee_rate)
            qty_by_risk = risk_budget / risk_per_unit
            equity_before = cash
            qty_by_exposure = (equity_before * max_exposure_percent) / (entry * (1 + fee_rate))
            qty_by_cash = cash / (entry * (1 + fee_rate))
            quantity = min(qty_by_risk, qty_by_exposure, qty_by_cash)
            if quantity > 0:
                entry_notional = quantity * entry
                entry_fee = entry_notional * fee_rate
                cash -= entry_notional + entry_fee
                position = {
                    "entry": entry, "stop": stop, "target": target,
                    "quantity": quantity, "entry_fee": entry_fee,
                    "opened_at": int(candle["timestamp"]),
                }

        # Entry occurs at the open, so the remaining OHLC range is eligible.
        if position is not None:
            exit_reason = None
            raw_exit = None
            if low <= position["stop"]:
                raw_exit = min(open_, position["stop"])
                exit_reason = "stop_loss"
            elif high >= position["target"]:
                raw_exit = max(open_, position["target"])
                exit_reason = "take_profit"
            elif i == len(candles) - 1:
                raw_exit = close
                exit_reason = "end_of_data"

            if exit_reason:
                exit_price = raw_exit * (1 - slippage_rate)
                proceeds = position["quantity"] * exit_price
                exit_fee = proceeds * fee_rate
                cash += proceeds - exit_fee
                pnl = (proceeds - exit_fee
                       - position["quantity"] * position["entry"]
                       - position["entry_fee"])
                trades.append({
                    **position,
                    "closed_at": int(candle["timestamp"]),
                    "exit_price": exit_price,
                    "exit_fee": exit_fee,
                    "net_pnl": pnl,
                    "reason": exit_reason,
                })
                position = None

        equity = cash
        if position is not None:
            mark = close
            equity += position["quantity"] * mark
        equity_curve.append({"timestamp": int(candle["timestamp"]), "equity": equity})
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    wins = sum(1 for trade in trades if trade["net_pnl"] > 0)
    gross_profit = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    gross_loss = -sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
    net_pnl = cash - float(initial_balance)
    return {
        "initial_balance": float(initial_balance),
        "final_equity": cash,
        "net_pnl": net_pnl,
        "return_percent": net_pnl / float(initial_balance) * 100,
        "trade_count": len(trades),
        "win_rate_percent": wins / len(trades) * 100 if trades else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (None if not gross_profit else float("inf")),
        "max_drawdown_percent": max_drawdown * 100,
        "fees_paid": sum(t["entry_fee"] + t["exit_fee"] for t in trades),
        "trades": trades,
        "equity_curve": equity_curve,
        "open_position_at_end": position is not None,
    }
