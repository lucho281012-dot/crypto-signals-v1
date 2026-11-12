
import os
import logging
import requests

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html import escape

from signal_tracker import load_history

# =========================================================
# CRYPTO SIGNALS - DAILY PERFORMANCE REPORT
# Informe diario de señales para Telegram.
# No ejecuta operaciones ni modifica el historial.
# =========================================================

TELEGRAM_URL = "https://api.telegram.org/bot{}/sendMessage"
REQUEST_TIMEOUT = 20

NICARAGUA_TZ = ZoneInfo("America/Managua")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

log = logging.getLogger("crypto-signals-daily-report")

SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


def local_signal_date(signal):
    """Obtiene la fecha local de emisión de una señal."""

    sent_at = signal.get("sent_at")

    if sent_at:
        dt = datetime.fromisoformat(
            str(sent_at).replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

    else:
        timestamp = int(signal["signal_candle_ts"])
        dt = datetime.fromtimestamp(
            timestamp / 1000,
            tz=timezone.utc
        )

    return dt.astimezone(NICARAGUA_TZ).date()


def get_counts(signals):
    """Calcula estadísticas sin modificar las señales."""

    counts = {
        "total": len(signals),
        "TP2": 0,
        "SL": 0,
        "SL_AFTER_TP1": 0,
        "AMBIGUOUS": 0,
        "ACTIVE": 0,
        "TP1": 0
    }

    for signal in signals:
        status = str(
            signal.get("status", "UNKNOWN")
        ).upper()

        if status in counts:
            counts[status] += 1

        if signal.get("tp1_hit") or signal.get("tp2_hit"):
            counts["TP1"] += 1

    counts["resolved"] = (
        counts["TP2"]
        + counts["SL"]
        + counts["SL_AFTER_TP1"]
    )

    if counts["resolved"]:
        counts["tp2_rate"] = (
            counts["TP2"] / counts["resolved"] * 100
        )
    else:
        counts["tp2_rate"] = 0

    return counts


def format_symbol_section(symbol, signals):
    """Prepara las estadísticas de un activo."""

    selected = [
        signal for signal in signals
        if signal.get("symbol") == symbol
    ]

    if not selected:
        return None

    counts = get_counts(selected)

    return (
        f"<b>{escape(symbol)}</b>\n"
        f"Señales: {counts['total']}\n"
        f"TP1 alcanzado: {counts['TP1']}\n"
        f"TP2: {counts['TP2']}\n"
        f"SL: {counts['SL']}\n"
        f"SL después de TP1: {counts['SL_AFTER_TP1']}\n"
        f"Activas: {counts['ACTIVE']}\n"
        f"Ambiguas: {counts['AMBIGUOUS']}\n"
        f"TP2 / resultados cerrados: "
        f"{counts['tp2_rate']:.1f}%"
    )


def build_report(history, report_date):
    """Construye el informe diario."""

    daily_signals = []

    for signal in history:
        try:
            if local_signal_date(signal) == report_date:
                daily_signals.append(signal)

        except Exception:
            log.exception(
                "No se pudo interpretar la fecha de una señal: %s",
                signal.get("id")
            )

    counts = get_counts(daily_signals)

    date_text = report_date.strftime("%d/%m/%Y")

    lines = [
        "📊 <b>CRYPTO SIGNALS NICARAGUA</b>",
        "📅 Informe diario: " + date_text,
        "",
        "<b>RESULTADOS DEL DÍA</b>",
        f"Señales emitidas: {counts['total']}",
        f"TP1 alcanzado: {counts['TP1']}",
        f"TP2: {counts['TP2']}",
        f"SL: {counts['SL']}",
        f"SL después de TP1: {counts['SL_AFTER_TP1']}",
        f"Activas: {counts['ACTIVE']}",
        f"Ambiguas: {counts['AMBIGUOUS']}",
        "",
        f"TP2 / resultados cerrados: "
        f"{counts['tp2_rate']:.1f}%",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "<b>RESULTADOS POR ACTIVO</b>",
        ""
    ]

    for symbol in SYMBOLS:
        section = format_symbol_section(
            symbol,
            daily_signals
        )

        if section:
            lines.append(section)
            lines.append("")

    if not daily_signals:
        lines.insert(
            3,
            "No se registraron señales durante este día."
        )

    # Estadística acumulada de todo el historial.
    total_counts = get_counts(history)

    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        "<b>ACUMULADO HISTÓRICO</b>",
        f"Señales registradas: {total_counts['total']}",
        f"TP1 alcanzado: {total_counts['TP1']}",
        f"TP2: {total_counts['TP2']}",
        f"SL: {total_counts['SL']}",
        f"SL después de TP1: {total_counts['SL_AFTER_TP1']}",
        f"Activas: {total_counts['ACTIVE']}",
        f"Ambiguas: {total_counts['AMBIGUOUS']}",
        "",
        "<i>Estadísticas de señales, no operaciones reales.</i>",
        "<i>TP2 / resultados cerrados excluye señales activas y ambiguas.</i>"
    ])

    return "\n".join(lines)


def send_telegram(message):
    """Envía el informe al Telegram configurado."""

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError(
            "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID."
        )

    response = requests.post(
        TELEGRAM_URL.format(token),
        json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        },
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram rechazó el informe: {result}"
        )

    log.info("Informe diario enviado correctamente.")


def main():
    log.info("=" * 55)
    log.info("CRYPTO SIGNALS - DAILY REPORT")
    log.info("=" * 55)

    now = datetime.now(NICARAGUA_TZ)
    report_date = now.date()

    history = load_history()

    message = build_report(
        history,
        report_date
    )

    log.info(
        "Preparando informe del %s",
        report_date.isoformat()
    )

    send_telegram(message)

    log.info("Proceso terminado correctamente.")


if __name__ == "__main__":
    main()
