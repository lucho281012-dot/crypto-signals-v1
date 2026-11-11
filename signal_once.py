
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

BASE_URL = "https://www.okx.com/api/v5/market/candles"

STATE_PATH = Path("data/state.json")
STATE_PATH.parent.mkdir(exist_ok=True)

TIMEOUT = 20
CANDLE_LIMIT = 300

HEADERS = {
    "User-Agent": "CryptoSignals-PaperTrading/1.0",
    "Accept": "application/json"
}

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
# DATOS DE OKX
# ==========================================

def okx_symbol(symbol):

    base, quote = symbol.upper().split("/")

    return f"{base}-{quote}-SWAP"


def frame(symbol, tf):

    instrument = okx_symbol(symbol)

    if tf not in ("5m", "15m"):
        raise ValueError(
            f"Temporalidad no soportada: {tf}"
        )

    params = {
        "instId": instrument,
        "bar": tf,
        "limit": str(CANDLE_LIMIT)
    }

    response = SESSION.get(
        BASE_URL,
        params=params,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    if data.get("code") != "0":
        raise RuntimeError(
            f"Error OKX {data.get('code')}: "
            f"{data.get('msg')}"
        )

    rows = data.get("data", [])

    if not rows:
        raise RuntimeError(
            f"OKX no devolvió velas para {instrument} {tf}"
        )

    # OKX:
    # 0 timestamp
    # 1 open
    # 2 high
    # 3 low
    # 4 close
    # 5 volume en contratos
    # 6 volume en moneda base
    # 7 volume en moneda cotizada
    # 8 confirm: 0 abierta, 1 cerrada

    closed = [
        row for row in rows
        if len(row) >= 9 and row[8] == "1"
    ]

    # Orden cronológico: antigua a reciente.
    closed.sort(
        key=lambda row: int(row[0])
    )

    if len(closed) < 210:
        raise RuntimeError(
            f"Datos insuficientes: {instrument} {tf}. "
            f"Velas cerradas: {len(closed)}"
        )

    df = pd.DataFrame(
        [
            [
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[6]
            ]
            for row in closed
        ],
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]
    )

    df["timestamp"] = pd.to_numeric(
        df["timestamp"],
        errors="raise"
    )

    for column in [
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]:
        df[column] = pd.to_numeric(
            df[column],
            errors="raise"
        )

    if not (df["volume"] > 0).all():
        raise RuntimeError(
            f"Volumen inválido en {instrument} {tf}"
        )

    if not (
        (df["high"] >= df["low"])
        & (df["high"] >= df["open"])
        & (df["high"] >= df["close"])
        & (df["low"] <= df["open"])
        & (df["low"] <= df["close"])
    ).all():
        raise RuntimeError(
            f"Precios OHLC inválidos en {instrument} {tf}"
        )

    return df.reset_index(drop=True)


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
        x["hist"] > 0 and x["hist"] >= prev["hist"],
        x.volume > x.volavg
    ]

    short = [
        x.close < x.ema200,
        x.close < x.ema20 and x.ema20 < prev.ema20,
        32 <= x.rsi <= 50,
        x["hist"] < 0 and x["hist"] <= prev["hist"],
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
    failures = []

    for symbol in SYMBOLS:

        try:

            log.info(
                "Consultando OKX: %s",
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

            # Registrar solo después de procesar correctamente.
            state["last_candle"][symbol] = candle

        except Exception as exc:

            failures.append(symbol)

            log.exception(
                "Error procesando %s: %s",
                symbol,
                exc
            )

        finally:

            time.sleep(0.5)

    save_state(state)

    if failures:
        raise RuntimeError(
            "Fallaron los siguientes activos: "
            + ", ".join(failures)
        )

    log.info(
        "Proceso Crypto Signals finalizado correctamente."
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:
        log.exception("Crypto Signals terminó con errores.")
        sys.exit(1)

    finally:
        SESSION.close()
