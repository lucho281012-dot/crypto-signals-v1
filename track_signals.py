
import logging
import time
import requests

from signal_tracker import load_history, save_history

# =========================================================
# CRYPTO SIGNALS V1.1 - PERFORMANCE TRACKER
# Evalúa señales con velas cerradas de OKX.
# No ejecuta operaciones ni envía órdenes.
# =========================================================

OKX_URL = "https://www.okx.com/api/v5/market/history-candles"

TIMEFRAME = "5m"
CANDLE_MS = 300000
CANDLE_LIMIT = 300
MAX_PAGES = 1000
REQUEST_TIMEOUT = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

log = logging.getLogger("crypto-signals-performance")


def fetch_page(symbol, after=None):
    """Obtiene una página de velas históricas de OKX."""

    params = {
        "instId": symbol.replace("/", "-"),
        "bar": TIMEFRAME,
        "limit": str(CANDLE_LIMIT)
    }

    if after is not None:
        params["after"] = str(after)

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

    return payload.get("data", [])


def parse_candles(rows):
    """Convierte las respuestas de OKX en velas cerradas."""

    candles = []

    for row in rows:
        if len(row) < 9:
            continue

        if str(row[8]) != "1":
            continue

        candles.append({
            "ts": int(row[0]),
            "high": float(row[2]),
            "low": float(row[3])
        })

    return candles


def fetch_closed_candles(symbol, earliest_ts):
    """
    Recupera todas las velas cerradas necesarias desde
    la fecha de inicio de seguimiento más antigua.
    """

    all_rows = []
    after = None
    previous_cursor = None

    for page_number in range(MAX_PAGES):

        rows = fetch_page(symbol, after)

        if not rows:
            break

        all_rows.extend(rows)

        timestamps = [
            int(row[0])
            for row in rows
            if len(row) >= 9
        ]

        if not timestamps:
            break

        oldest_ts = min(timestamps)

        if oldest_ts <= earliest_ts:
            break

        if previous_cursor == oldest_ts:
            raise RuntimeError(
                f"OKX no avanzó en la paginación de {symbol}"
            )

        previous_cursor = oldest_ts
        after = str(oldest_ts)

        time.sleep(0.15)

    else:
        raise RuntimeError(
            f"Se alcanzó el límite de páginas para {symbol}. "
            "No se garantiza la cobertura histórica completa."
        )

    candles = parse_candles(all_rows)

    # Eliminar duplicados por timestamp.
    unique = {
        candle["ts"]: candle
        for candle in candles
    }

    candles = sorted(
        unique.values(),
        key=lambda candle: candle["ts"]
    )

    if not candles:
        raise RuntimeError(
            f"No hay velas cerradas para {symbol}"
        )

    if candles[0]["ts"] > earliest_ts:
        raise RuntimeError(
            f"Historial insuficiente para {symbol}. "
            f"Se necesita desde {earliest_ts}, "
            f"pero la primera vela disponible es "
            f"{candles[0]['ts']}."
        )

    return candles


def candle_hits_levels(signal, candle):
    """Determina los niveles tocados en una vela."""

    side = signal["side"].upper()

    stop = float(signal["stop"])
    tp1 = float(signal["tp1"])
    tp2 = float(signal["tp2"])

    if side == "SHORT":
        stop_hit = candle["high"] >= stop
        tp1_hit = candle["low"] <= tp1
        tp2_hit = candle["low"] <= tp2

    elif side == "LONG":
        stop_hit = candle["low"] <= stop
        tp1_hit = candle["high"] >= tp1
        tp2_hit = candle["high"] >= tp2

    else:
        raise ValueError(f"Dirección inválida: {side}")

    return stop_hit, tp1_hit, tp2_hit


def evaluate_signal(signal, candles):
    """
    Evalúa velas posteriores a la señal y procesa únicamente
    secuencias continuas de velas de cinco minutos.
    """

    if signal.get("status") != "ACTIVE":
        return False

    start_ts = int(signal["start_tracking_ts"])

    last_checked = signal.get("last_checked_ts")

    if last_checked is None:
        expected_ts = start_ts
    else:
        expected_ts = int(last_checked) + CANDLE_MS

    pending = [
        candle for candle in candles
        if candle["ts"] >= expected_ts
    ]

    if not pending:
        return False

    changed = False

    for candle in pending:

        # No avanzar sobre huecos de datos.
        if candle["ts"] != expected_ts:
            log.warning(
                "Hueco de velas para %s. "
                "Esperada: %s | Recibida: %s",
                signal["id"],
                expected_ts,
                candle["ts"]
            )
            break

        stop_hit, tp1_hit, tp2_hit = candle_hits_levels(
            signal,
            candle
        )

        previous_tp1 = bool(signal.get("tp1_hit", False))

        signal["last_checked_ts"] = candle["ts"]
        changed = True

        # Si SL y TP2 se tocan en la misma vela,
        # no conocemos el orden intravela.
        #
        # Si TP1 ya había ocurrido anteriormente,
        # tocar nuevamente TP1 junto al SL no es ambiguo.
        ambiguous = stop_hit and (
            tp2_hit or (tp1_hit and not previous_tp1)
        )

        if ambiguous:
            signal["status"] = "AMBIGUOUS"
            signal["result"] = "AMBIGUOUS_SL_AND_TARGET"

            log.warning(
                "Resultado ambiguo: %s | Vela: %s",
                signal["id"],
                candle["ts"]
            )
            break

        # Stop Loss.
        if stop_hit:

            if previous_tp1:
                signal["status"] = "SL_AFTER_TP1"
                signal["result"] = "SL_AFTER_TP1"
            else:
                signal["status"] = "SL"
                signal["result"] = "SL"

            log.info(
                "Stop Loss alcanzado: %s",
                signal["id"]
            )
            break

        # TP2 también implica TP1.
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
        if tp1_hit and not previous_tp1:
            signal["tp1_hit"] = True

            log.info(
                "TP1 alcanzado: %s",
                signal["id"]
            )

        expected_ts += CANDLE_MS

    return changed


def main():

    log.info("=" * 60)
    log.info("CRYPTO SIGNALS - PERFORMANCE TRACKER")
    log.info("=" * 60)

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

    # Obtener la fecha más antigua necesaria por símbolo.
    earliest_by_symbol = {}

    for signal in active_signals:
        symbol = signal["symbol"]
        start_ts = int(signal["start_tracking_ts"])

        if (
            symbol not in earliest_by_symbol
            or start_ts < earliest_by_symbol[symbol]
        ):
            earliest_by_symbol[symbol] = start_ts

    candles_by_symbol = {}
    failures = []

    # Consultar OKX una vez por activo.
    for symbol, earliest_ts in earliest_by_symbol.items():

        try:
            log.info(
                "Consultando OKX: %s | Desde: %s",
                symbol,
                earliest_ts
            )

            candles = fetch_closed_candles(
                symbol,
                earliest_ts
            )

            candles_by_symbol[symbol] = candles

            log.info(
                "%s: %s velas cerradas recuperadas",
                symbol,
                len(candles)
            )

        except Exception:
            failures.append(symbol)
            log.exception(
                "Error consultando OKX para %s",
                symbol
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
            failures.append(signal.get("id"))

            log.exception(
                "Error evaluando señal %s",
                signal.get("id")
            )

    # Guardar cualquier avance realizado.
    if changed_count > 0:
        save_history(history)

        log.info(
            "Historial guardado. Señales actualizadas: %s",
            changed_count
        )

    # Resumen general.
    counts = {}

    for signal in history:
        status = signal.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1

    log.info("-" * 60)
    log.info("RESUMEN DEL SEGUIMIENTO")

    for status, count in sorted(counts.items()):
        log.info("%s: %s", status, count)

    log.info(
        "Señales actualizadas: %s",
        changed_count
    )

    log.info(
        "Errores de consulta o evaluación: %s",
        len(failures)
    )

    log.info("=" * 60)

    if failures:
        raise RuntimeError(
            "El seguimiento terminó con errores. "
            "Revisa los registros antes de confiar "
            "en el resultado."
        )


if __name__ == "__main__":
    main()
