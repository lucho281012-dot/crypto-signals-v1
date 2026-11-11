
import os
import json
import logging
import time
import sys

from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import requests


# ==========================================
# CONFIGURACIÓN
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

log = logging.getLogger("crypto-signals")

SYMBOLS = [
    s.strip()
    for s in os.getenv(
        "SYMBOLS",
        "BTC/USDT,ETH/USDT,SOL/USDT"
    ).split(",")
    if s.strip()
]

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MIN_SCORE = int(os.getenv("MIN_SCORE", "4"))
ATR_MULT = float(os.getenv("ATR_MULTIPLIER", "1.2"))

BASE_URL = "https://api.bybit.com/v5/market/kline"

STATE_PATH = Path("data/state.json")
STATE_PATH.parent.mkdir(exist_ok=True)

TIMEOUT = 20
CANDLE_LIMIT = 250

HEADERS = {
    "User-Agent": "CryptoSignals-PaperTrading/1.0",
    "Accept": "application/json"
}


# ==========================================
# SESIÓN HTTP
# ==========================================

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ==========================================
# ESTADO DEL BOT
# ==========================================

def load_state():

    try:
        state = json.loads(STATE_PATH.read_text())

        if not isinstance(state.get("last_candle"), dict):
            state["last_candle"] = {}

        return state

    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_candle": {}}


def save_state(state):

    STATE_PATH.write_text(
        json.dumps(state, indent=2)
    )


# ==========================================
# TELEGRAM
# ==========================================

def notify(msg):

    response = SESSION.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": msg,
            "disable_web_page_preview": True
        },
        timeout=TIMEOUT
    )

    response.raise_for_status()

    if not response.json().get("ok"):
        raise RuntimeError(response.text)


# ==========================================
# DATOS DE BYBIT
# ==========================================

def frame(symbol, tf):

    bybit_symbol = symbol.replace("/", "").upper()

    interval = {
        "5m": "5",
        "15m": "15"
    }.get(tf)

    if interval is None:
        raise ValueError(f"Temporalidad no soportada: {tf}")

    params = {
        "category": "linear",
        "symbol": bybit_symbol,
        "interval": interval,
        "limit": CANDLE_LIMIT
    }

    response = SESSION.get(
        BASE_URL,
        params=params,
        timeout=TIMEOUT
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Error HTTP Bybit {response.status_code}: "
            f"{response.text[:1000]}"
        )

    data = response.json()

    if data.get("retCode") != 0:
        raise RuntimeError(
            f"Error Bybit {data.get('retCode')}: "
            f"{data.get('retMsg')}"
        )

    rows = data.get("result", {}).get("list", [])

    if not rows:
        raise RuntimeError(
            f"Bybit no devolvió velas para {symbol} {tf}"
        )

    # Bybit entrega las velas de más reciente a más antigua.
    rows = sorted(
        rows,
        key=lambda row: int(row[0])
    )

    df = pd.DataFrame(
        rows,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover"
        ]
    )

    df = df[
        ["timestamp", "open", "high", "low", "close", "volume"]
    ].copy()

    df["timestamp"] = pd.to_numeric(
        df["timestamp"],
        errors="raise"
    )

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(
            df[column],
            errors="raise"
        )

    # Excluir la vela más reciente, que puede estar abierta.
    df = df.iloc[:-1].copy().reset_index(drop=True)

    if len(df) < 210:
        raise RuntimeError(
            f"Datos insuficientes: {symbol} {tf}. "
            f"Velas cerradas recibidas: {len(df)}"
        )

    return df


# ==========================================
# INDICADORES
# ==========================================

def ind(df):

    c = df.close
    h = df.high
    l = df.low
    v = df.volume

    df["ema20"] = c.ewm(
        span=20,
        adjust=False
    ).mean()

    df["ema200"] = c.ewm(
        span=200,
        adjust=False
    ).mean()

    d = c.diff()

    up = d.clip(lower=0).ewm(
        alpha=1/14,
        adjust=False,
        min_periods=14
    ).mean()

    dn = (-d.clip(upper=0)).ewm(
        alpha=1/14,
        adjust=False,
        min_periods=14
    ).mean()

    df["rsi"] = 100 - 100 / (
        1 + up / dn.replace(0, 1e-12)
    )

    m = (
        c.ewm(span=12, adjust=False).mean()
        - c.ewm(span=26, adjust=False).mean()
    )

    df["hist"] = (
        m - m.ewm(span=9, adjust=False).mean()
    )

    pc = c.shift(1)

    tr = pd.concat(
        [
            h - l,
            (h - pc).abs(),
            (l - pc).abs()
        ],
        axis=1
    ).max(axis=1)

    df["atr"] = tr.ewm(
        alpha=1/14,
        adjust=False,
        min_periods=14
    ).mean()

    df["volavg"] = v.rolling(20).mean()

    return df


# ==========================================
# ANÁLISIS DE SEÑALES
# ==========================================

def analyze(d5, d15):

    z = ind(d5)

    x = z.iloc[-1]
    prev = z.iloc[-2]

    y = ind(d15).iloc[-1]

    if (
        pd.isna(x.atr)
        or pd.isna(x.rsi)
        or pd.isna(x.volavg)
        or x.atr <= 0
        or x.volavg <= 0
    ):
        return None

    long = [
        x.close > x.ema200,
        x.close > x.ema20 and x.ema20 > prev.ema20,
        50 <= x.rsi <= 68,
        x.hist > 0 and x.hist >= prev.hist,
        x.volume > x.volavg
    ]

    short = [
        x.close < x.ema200,
        x.close < x.ema20 and x.ema20 < prev.ema20,
        32 <= x.rsi <= 50,
        x.hist < 0 and x.hist <= prev.hist,
        x.volume > x.volavg
    ]

    lc = y.close > y.ema200 and y.ema20 > y.ema200
    sc = y.close < y.ema200 and y.ema20 < y.ema200

    ls = sum(long)
    ss = sum(short)

    if ls >= MIN_SCORE and lc and ls > ss:
        side, score = "LONG", ls

    elif ss >= MIN_SCORE and sc and ss > ls:
        side, score = "SHORT", ss

    else:
        return None

    entry = float(x.close)
    dist = float(x.atr) * ATR_MULT

    if side == "LONG":
        stop = entry - dist
        tp1 = entry + dist
        tp2 = entry + 2 * dist

    else:
        stop = entry + dist
        tp1 = entry - dist
        tp2 = entry - 2 * dist

    return {
        "side": side,
        "score": score,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "rsi": float(x.rsi),
        "vol": float(x.volume / x.volavg),
        "ts": int(d5.iloc[-1].timestamp)
    }


# ==========================================
# FORMATO DE PRECIOS
# ==========================================

def fmt(x):

    return f"{x:,.6f}".rstrip("0").rstrip(".")


# ==========================================
# EJECUCIÓN PRINCIPAL
# ==========================================

def main():

    state = load_state()

    for symbol in SYMBOLS:

        try:

            log.info(
                "Consultando Bybit: %s",
                symbol
            )

            d5 = frame(symbol, "5m")

            candle = int(
                d5.iloc[-1].timestamp
            )

            if state["last_candle"].get(symbol) == candle:

                log.info(
                    "%s: vela ya procesada",
                    symbol
                )

                continue

            d15 = frame(symbol, "15m")

            sig = analyze(d5, d15)

            if sig:

                dt = datetime.fromtimestamp(
                    sig["ts"] / 1000,
                    timezone.utc
                ).strftime("%Y-%m-%d %H:%M UTC")

                icon = (
                    "🟢"
                    if sig["side"] == "LONG"
                    else "🔴"
                )

                msg = (
                    f"{icon} CRYPTO SIGNALS V1.1\n"
                    f"{symbol} · {sig['side']}\n"
                    "Temporalidades: 5m + confirmación 15m\n"
                    f"Entrada ref.: {fmt(sig['entry'])}\n"
                    f"Stop Loss: {fmt(sig['stop'])}\n"
                    f"TP1 (1R): {fmt(sig['tp1'])}\n"
                    f"TP2 (2R): {fmt(sig['tp2'])}\n"
                    f"Filtros: {sig['score']}/5 · "
                    f"RSI: {sig['rsi']:.1f}\n"
                    f"Volumen/promedio: {sig['vol']:.2f}x\n"
                    f"Vela cerrada: {dt}\n"
                    "Alerta informativa; no garantiza resultados. "
                    "Verifica el precio antes de actuar."
                )

                notify(msg)

                log.info(
                    "Señal enviada: %s %s",
                    symbol,
                    sig["side"]
                )

            else:

                log.info(
                    "%s: sin señal",
                    symbol
                )

            # Registrar solamente después de procesar correctamente.
            state["last_candle"][symbol] = candle

        except Exception:

            log.exception(
                "Error con %s",
                symbol
            )

        finally:

            time.sleep(0.5)

    save_state(state)

    log.info(
        "Proceso Crypto Signals finalizado."
    )


if __name__ == "__main__":

    try:
        main()

    finally:
        SESSION.close()
