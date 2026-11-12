
import logging
import time
import requests

from signal_tracker import load_history, save_history

# =========================================================
# CRYPTO SIGNALS V1.1 - PERFORMANCE TRACKER
# Evalúa señales usando velas cerradas de OKX.
# No ejecuta operaciones ni envía órdenes.
# =========================================================

OKX_URL = "https://www.okx.com/api/v5/market/candles"
TIMEFRAME = "5m"
CANDLE_LIMIT = 300
REQUEST_TIMEOUT = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

log = logging.getLogger("crypto-signals-performance")


def fetch_closed_candles(symbol):
    """Obtiene velas cerradas de 5 minutos desde OKX."""

    inst_id = symbol.replace("/", "-")

    params = {
        "instId": inst_id,
        "bar": TIMEFRAME,
        "limit": str(CANDLE_LIMIT)
    }

    response = requests.get(
        OKX_URL,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    payload = response.json()

    if payload.get("code") != "0":
        raise RuntimeError(
            f"Error OKX para {symbol}: {payload.get('msg')}"
        )

    rows = payload.get("data", [])

    candles = []

    for row in rows:
        if len(row) < 9:
            continue

        # OKX: timestamp, open, high, low, close, ..., confirm
        if str(row[8]) != "1":
            continue

        candles.append({
            "ts": int(row[0]),
            "high": float(row[2]),
            "low": float(row[3])
        })

    candles.sort(key=lambda candle: candle["ts"])

    if not candles:
        raise RuntimeError(
            f"OKX no devolvió velas cerradas para {symbol}"
        )

    return candles


def candle_hits_levels(signal, candle):
    """Determina qué niveles fueron tocados en una vela."""

    side = signal["side"].upper()

    if side == "SHORT":
        stop_hit = candle["high"] >= float(signal["stop"])
        tp1_hit = candle["low"] <= float(signal["tp1"])
        tp2_hit = candle["low"] <= float(signal["tp2"])

    elif side == "LONG":
        stop_hit = candle["low"] <= float(signal["stop"])
        tp1_hit = candle["high"] >= float(signal["tp1"])
        tp2_hit = candle["high"] >= float(signal["tp2"])

    else:
        raise ValueError(f"Dirección inválida: {side}")

    return stop_hit, tp1_hit, tp2_hit


def evaluate_signal(signal, candles):
    """Actualiza una señal usando únicamente velas posteriores."""

    if signal.get("status") != "ACTIVE":
        return False

    start_ts = int(signal["start_tracking_ts"])

    last_checked = signal.get("last_checked_ts")
    if last_checked is not None:
        last_checked = int(last_checked)

    # Solo se procesan velas posteriores a la señal
    # y posteriores al último chequeo guardado.
    pending = [
        candle for candle in candles
        if candle["ts"] >= start_ts
        and (
            last_checked is None
            or candle["ts"] > last_checked
        )
    ]

    if not pending:
        return False

    changed = False

    for candle in pending:
        stop_hit, tp1_hit, tp2_hit = candle_hits_levels(
            signal,
            candle
        )

        signal["last_checked_ts"] = candle["ts"]
        changed = True

        # Si SL y algún objetivo aparecen en la misma vela,
        # no podemos conocer el orden intravela.
        if stop_hit and (tp1_hit or tp2_hit):
            signal["status"] = "AMBIGUOUS"
            signal["result"] = "AMBIGUOUS_SL_AND_TARGET"

            log.warning(
                "Resultado ambiguo: %s | vela %s",
                signal["id"],
                candle["ts"]
            )
            break

        # Stop Loss
        if stop_hit:
            if signal.get("tp1_hit"):
                signal["status"] = "SL_AFTER_TP1"
                signal["result"] = "SL_AFTER_TP1"
            else:
                signal["status"] = "SL"
                signal["result"] = "SL"

            log.info(
                "SL alcanzado: %s",
                signal["id"]
            )
            break

        # TP2 implica que TP1 también fue alcanzado.
        if tp2_hit:
            signal["tp1_hit"] = True
            signal["tp2_hit"] = True
            signal["status"] = "TP2"
            signal["result"] = "TP2"

            log.info(
                "TP2 alcanzado: %s",
                signal["id"]
            )
            break

        # TP1 es un hito; la señal continúa activa.
        if tp1_hit and not signal.get("tp1_hit"):
            signal["tp1_hit"] = True

            log.info(
                "TP1 alcanzado: %s",
                signal["id"]
            )

    return changed


def main():
    log.info("=" * 55)
    log.info("CRYPTO SIGNALS - PERFORMANCE TRACKER")
    log.info("=" * 55)

    history = load_history()

    if not history:
        log.info("No hay señales registradas.")
        return

    active_signals = [
        signal for signal in history
        if signal.get("status") == "ACTIVE"
    ]

    if not active_signals:
        log.info("No hay señales activas para evaluar.")
        return

    symbols = sorted({
        signal["symbol"]
        for signal in active_signals
    })

    candles_by_symbol = {}
    failures = []

    # Consultar OKX una vez por activo.
    for symbol in symbols:
        try:
            log.info("Consultando OKX: %s", symbol)

            candles_by_symbol[symbol] = fetch_closed_candles(
                symbol
            )

            log.info(
                "%s: %s velas cerradas recibidas",
                symbol,
                len(candles_by_symbol[symbol])
            )

        except Exception as exc:
            failures.append(symbol)
            log.exception(
                "Error consultando %s: %s",
                symbol,
                exc
            )

        time.sleep(0.3)

    changed_count = 0

    # Evaluar cada señal por separado.
    for signal in active_signals:
        symbol = signal["symbol"]

        if symbol not in candles_by_symbol:
            continue

        try:
            changed = evaluate_signal(
                signal,
                candles_by_symbol[symbol]
            )

            if changed:
                changed_count += 1

        except Exception:
            log.exception(
                "Error evaluando señal %s",
                signal.get("id")
            )
            failures.append(signal.get("id"))

    # Guardar incluso si alguna consulta falló,
    # conservando los resultados que sí se pudieron evaluar.
    if changed_count > 0:
        save_history(history)

    # Resumen
    counts = {}

    for signal in history:
        status = signal.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1

    log.info("-" * 55)
    log.info("RESUMEN DEL SEGUIMIENTO")

    for status, count in sorted(counts.items()):
        log.info("%s: %s", status, count)

    log.info(
        "Señales actualizadas: %s",
        changed_count
    )

    log.info(
        "Consultas o evaluaciones con errores: %s",
        len(failures)
    )

    log.info("=" * 55)

    if failures:
        raise RuntimeError(
            "El seguimiento terminó con errores. "
            "Revisa el registro antes de confiar en el resultado."
        )


if __name__ == "__main__":
    main()
