"""Strict importer/validator for Kraken downloadable OHLCVT CSV files.

Kraken files are headerless rows:
timestamp, open, high, low, close, volume, trades
Timestamps are Unix seconds. Missing intervals are never synthesized.
"""
import csv
import hashlib
import math
from pathlib import Path


def _finite_positive(value, field, line_number, allow_zero=False):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Fila {line_number}: {field} no numérico") from exc
    if not math.isfinite(number):
        raise ValueError(f"Fila {line_number}: {field} no finito")
    if number < 0 if allow_zero else number <= 0:
        raise ValueError(f"Fila {line_number}: {field} fuera de rango")
    return number


def load_kraken_ohlcvt_csv(path, timeframe_minutes, require_contiguous=True):
    """Load one Kraken OHLCVT CSV and return normalized candles + provenance.

    Output timestamps are milliseconds since Unix epoch, matching CCXT.
    When require_contiguous=False, gaps are reported in metadata but not filled.
    """
    if isinstance(timeframe_minutes, bool) or int(timeframe_minutes) <= 0:
        raise ValueError("timeframe_minutes debe ser un entero positivo")
    timeframe_minutes = int(timeframe_minutes)
    interval_seconds = timeframe_minutes * 60
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    digest = hashlib.sha256()
    with source.open("rb") as binary_file:
        for chunk in iter(lambda: binary_file.read(1024 * 1024), b""):
            digest.update(chunk)

    candles = []
    previous_timestamp = None
    gap_count = 0
    first_gap = None

    with source.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.reader(csv_file)
        for line_number, row in enumerate(reader, start=1):
            if not row or all(not field.strip() for field in row):
                continue
            if len(row) != 7:
                raise ValueError(
                    f"Fila {line_number}: se esperaban 7 columnas OHLCVT, "
                    f"se recibieron {len(row)}"
                )
            try:
                timestamp_value = float(row[0])
            except ValueError as exc:
                raise ValueError(
                    f"Fila {line_number}: timestamp Unix inválido"
                ) from exc
            if not math.isfinite(timestamp_value) or not timestamp_value.is_integer():
                raise ValueError(f"Fila {line_number}: timestamp debe ser entero")
            timestamp_seconds = int(timestamp_value)
            if timestamp_seconds < 0 or timestamp_seconds % interval_seconds:
                raise ValueError(
                    f"Fila {line_number}: timestamp no alineado a "
                    f"{timeframe_minutes}m"
                )
            if previous_timestamp is not None:
                if timestamp_seconds <= previous_timestamp:
                    raise ValueError(
                        f"Fila {line_number}: timestamps duplicados o desordenados"
                    )
                delta = timestamp_seconds - previous_timestamp
                if delta % interval_seconds:
                    raise ValueError(
                        f"Fila {line_number}: intervalo temporal no múltiplo "
                        "del timeframe"
                    )
                missing = delta // interval_seconds - 1
                if missing:
                    gap_count += missing
                    if first_gap is None:
                        first_gap = {
                            "after_timestamp": previous_timestamp * 1000,
                            "before_timestamp": timestamp_seconds * 1000,
                            "missing_intervals": missing,
                        }

            open_ = _finite_positive(row[1], "open", line_number)
            high = _finite_positive(row[2], "high", line_number)
            low = _finite_positive(row[3], "low", line_number)
            close = _finite_positive(row[4], "close", line_number)
            volume = _finite_positive(row[5], "volume", line_number, allow_zero=True)
            trades_value = _finite_positive(
                row[6], "trades", line_number, allow_zero=True
            )
            if not trades_value.is_integer():
                raise ValueError(f"Fila {line_number}: trades debe ser entero")
            if high < max(open_, close, low) or low > min(open_, close, high):
                raise ValueError(f"Fila {line_number}: OHLC inconsistente")
            if trades_value == 0 and volume != 0:
                raise ValueError(
                    f"Fila {line_number}: volumen positivo con cero operaciones"
                )

            candles.append({
                "timestamp": timestamp_seconds * 1000,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "trades": int(trades_value),
            })
            previous_timestamp = timestamp_seconds

    if not candles:
        raise ValueError("El CSV no contiene velas OHLCVT")

    if require_contiguous and gap_count:
        raise ValueError(
            f"Se detectaron {gap_count} intervalos sin operaciones; "
            "no se rellenaron. Usa require_contiguous=False para inspeccionar "
            "el conjunto sin hacerlo apto para el adaptador de señales."
        )

    metadata = {
        "exchange": "Kraken",
        "source_file": source.name,
        "source_sha256": digest.hexdigest(),
        "timeframe_minutes": timeframe_minutes,
        "row_count": len(candles),
        "first_timestamp_ms": candles[0]["timestamp"],
        "last_timestamp_ms": candles[-1]["timestamp"],
        "missing_intervals": gap_count,
        "first_gap": first_gap,
        "gaps_filled": False,
    }
    return {"candles": candles, "metadata": metadata}
