#!/usr/bin/env python3
"""Read-only paper-trading preflight. Never imports paper_trading or writes state."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
TIMEFRAME_MS = {"5m": 300_000, "15m": 900_000}
MAX_AGE_SECONDS = {"5m": 15 * 60, "15m": 30 * 60}


def validate_candles(candles, timeframe, now):
    if not isinstance(candles, list) or len(candles) < 200:
        raise ValueError(f"{timeframe}: se requieren al menos 200 velas")
    step = TIMEFRAME_MS[timeframe]
    timestamps = []
    for index, candle in enumerate(candles):
        try:
            ts = int(candle["timestamp"])
            o, h, low, close, volume = (
                float(candle["open"]), float(candle["high"]),
                float(candle["low"]), float(candle["close"]),
                float(candle["volume"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{timeframe}: vela {index} incompleta o inválida") from exc
        if ts % step:
            raise ValueError(f"{timeframe}: timestamp no alineado a {timeframe}: {ts}")
        if min(o, h, low, close) <= 0 or volume < 0:
            raise ValueError(f"{timeframe}: OHLCV fuera de rango en vela {index}")
        if h < max(o, close, low) or low > min(o, close, h):
            raise ValueError(f"{timeframe}: OHLC inconsistente en vela {index}")
        timestamps.append(ts)
    if timestamps != sorted(set(timestamps)):
        raise ValueError(f"{timeframe}: timestamps duplicados o desordenados")
    closed_ts = timestamps[-2]  # La última vela puede seguir abierta.
    age = (now.timestamp() * 1000 - closed_ts) / 1000
    if age < -60 or age > MAX_AGE_SECONDS[timeframe]:
        raise ValueError(
            f"{timeframe}: última vela cerrada no está fresca (edad {age:.0f}s)"
        )
    return closed_ts


def run_preflight(fetch_market_data, analyze_signal, state_path, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now debe incluir zona horaria")
    state_bytes = Path(state_path).read_bytes()
    state = json.loads(state_bytes)
    if state.get("positions", {}):
        raise ValueError("Hay posiciones abiertas; preflight detenido por seguridad")
    checkpoints = state.get("last_processed_candle", {})
    if not isinstance(checkpoints, dict):
        raise ValueError("last_processed_candle inválido")

    market = fetch_market_data()
    report = {
        "mode": "READ_ONLY_PREFLIGHT",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "state_file_unchanged": True,
        "cash_usdt": state.get("cash_usdt"),
        "closed_trades": len(state.get("history", [])),
        "open_positions": len(state.get("positions", {})),
        "symbols": {}
    }
    for symbol in SYMBOLS:
        if symbol not in market:
            raise ValueError(f"Sin datos de mercado para {symbol}")
        data = market[symbol]
        ts5 = validate_candles(data.get("candles_5m"), "5m", now)
        ts15 = validate_candles(data.get("candles_15m"), "15m", now)
        price = float(data.get("price", 0))
        if price <= 0:
            raise ValueError(f"Precio inválido para {symbol}")
        old_checkpoint = int(checkpoints.get(symbol, 0))
        if ts5 < old_checkpoint:
            raise ValueError(f"Checkpoint futuro respecto a Kraken para {symbol}")
        signal = analyze_signal(data["candles_5m"], data["candles_15m"])
        report["symbols"][symbol] = {
            "price": price,
            "last_closed_5m_utc": datetime.fromtimestamp(ts5 / 1000, timezone.utc).isoformat(),
            "last_closed_15m_utc": datetime.fromtimestamp(ts15 / 1000, timezone.utc).isoformat(),
            "checkpoint_status": "new_closed_candle_available" if ts5 > old_checkpoint else "already_at_checkpoint",
            "signal": signal if signal else None
        }
    if Path(state_path).read_bytes() != state_bytes:
        raise RuntimeError("El archivo de estado cambió durante el preflight")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path", default="data/paper_state.json")
    args = parser.parse_args()
    from market_data import get_all_market_data
    from signal_engine import analyze_spot
    report = run_preflight(get_all_market_data, analyze_spot, args.state_path)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
