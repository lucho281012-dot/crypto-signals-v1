
import json
import logging
import os
import tempfile

from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("crypto-signals-tracker")

HISTORY_PATH = Path("data/signals_history.json")


def load_history():
    """Carga el historial sin sobrescribir registros existentes."""
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("El historial no tiene el formato esperado.")
        return data
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"El historial de señales está dañado: {exc}"
        ) from exc


def save_history(history):
    """Guarda el historial de forma atómica."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        dir=str(HISTORY_PATH.parent),
        prefix="signals_",
        suffix=".tmp"
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(history, file, indent=2, ensure_ascii=False)
            file.write("\n")

        os.replace(temp_path, HISTORY_PATH)

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def record_signal(symbol, signal):
    """
    Registra una señal únicamente después de enviarla correctamente
    a Telegram.

    La vela que generó la señal no se evalúa como resultado.
    """
    required = ("side", "entry", "stop", "tp1", "tp2", "ts")

    for field in required:
        if field not in signal:
            raise ValueError(f"Falta el dato obligatorio: {field}")

    side = str(signal["side"]).upper()

    if side not in ("LONG", "SHORT"):
        raise ValueError(f"Dirección inválida: {side}")

    candle_ts = int(signal["ts"])

    signal_id = f"{symbol.replace('/', '-')}-{side}-{candle_ts}"

    history = load_history()

    # Evita registrar dos veces la misma señal.
    if any(item.get("id") == signal_id for item in history):
        log.info("Señal ya registrada: %s", signal_id)
        return False

    record = {
        "id": signal_id,
        "symbol": symbol,
        "side": side,
        "timeframe": "5m",
        "signal_candle_ts": candle_ts,
        "start_tracking_ts": candle_ts + 300000,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "entry": float(signal["entry"]),
        "stop": float(signal["stop"]),
        "tp1": float(signal["tp1"]),
        "tp2": float(signal["tp2"]),
        "score": int(signal.get("score", 0)),
        "rsi": float(signal.get("rsi", 0)),
        "volume_ratio": float(signal.get("vol", 0)),
        "tp1_hit": False,
        "tp2_hit": False,
        "status": "ACTIVE",
        "result": None,
        "last_checked_ts": None
    }

    history.append(record)
    save_history(history)

    log.info("Señal registrada para seguimiento: %s", signal_id)
    return True
