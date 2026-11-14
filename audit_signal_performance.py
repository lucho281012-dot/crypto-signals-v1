import argparse
import json
import math
import sys
from pathlib import Path

STATUSES = {"ACTIVE", "TP2", "SL", "SL_AFTER_TP1", "AMBIGUOUS"}
SCENARIOS = {
    "no_partial": -1.0,
    "half_at_tp1_half_at_break_even": 0.5,
    "half_at_tp1_half_at_original_stop": 0.0,
}


def validate(history):
    if not isinstance(history, list):
        raise ValueError("El historial debe ser una lista JSON")
    seen = set()
    for i, item in enumerate(history):
        if not isinstance(item, dict):
            raise ValueError("Registro no es objeto: " + str(i))
        sid = str(item.get("id", "index:" + str(i)))
        required = ("id", "symbol", "side", "entry", "stop", "tp1", "tp2", "status")
        missing = [key for key in required if key not in item]
        if missing:
            raise ValueError(sid + ": faltan campos " + ", ".join(missing))
        if sid in seen:
            raise ValueError("ID duplicado: " + sid)
        seen.add(sid)
        side = str(item["side"]).upper()
        status = str(item["status"]).upper()
        if side not in ("LONG", "SHORT"):
            raise ValueError(sid + ": dirección inválida")
        if status not in STATUSES:
            raise ValueError(sid + ": estado desconocido " + status)
        values = {}
        for key in ("entry", "stop", "tp1", "tp2"):
            try:
                values[key] = float(item[key])
            except (TypeError, ValueError):
                raise ValueError(sid + ": precio inválido " + key)
            if not math.isfinite(values[key]):
                raise ValueError(sid + ": precio no finito " + key)
        entry, stop, tp1, tp2 = (values[k] for k in ("entry", "stop", "tp1", "tp2"))
        risk = abs(entry - stop)
        if entry <= 0 or risk <= 0:
            raise ValueError(sid + ": entry/riesgo debe ser positivo")
        ordered = stop < entry < tp1 < tp2 if side == "LONG" else stop > entry > tp1 > tp2
        if not ordered:
            raise ValueError(sid + ": niveles incompatibles con " + side)
        if not math.isclose(abs(tp1-entry), risk, rel_tol=1e-5, abs_tol=1e-8):
            raise ValueError(sid + ": TP1 no corresponde a 1R")
        if not math.isclose(abs(tp2-entry), 2*risk, rel_tol=1e-5, abs_tol=1e-8):
            raise ValueError(sid + ": TP2 no corresponde a 2R")
    return history


def fee_r(item, fee_bps):
    if fee_bps is None:
        return None
    risk = abs(float(item["entry"]) - float(item["stop"]))
    return 2 * (fee_bps / 10000) * float(item["entry"]) / risk


def metrics(records, fee_bps):
    definite = [r for r in records if r["status"] in ("TP2", "SL")]
    gross = [2.0 if r["status"] == "TP2" else -1.0 for r in definite]
    fees = [fee_r(r, fee_bps) for r in definite]
    net = [g-f for g, f in zip(gross, fees)] if fee_bps is not None else None
    # Losing streaks are calculated within each symbol. Pooling symbols can
    # create artificial streaks when multiple assets signal on the same candle.
    by_asset = {}
    for record in records:
        by_asset.setdefault(str(record["symbol"]), []).append(record)
    maximum = 0
    for asset_records in by_asset.values():
        ordered = sorted(
            asset_records,
            key=lambda r: (int(r.get("signal_candle_ts", 0)), str(r["id"])),
        )
        streak = 0
        for record in ordered:
            streak = streak + 1 if record["status"] == "SL" else 0
            maximum = max(maximum, streak)
    partial_records = [r for r in records if r["status"] in ("TP2", "SL", "SL_AFTER_TP1")]
    scenario_sensitivity = {}
    for scenario, scenario_r in SCENARIOS.items():
        scenario_total = sum(gross) + scenario_r * sum(r["status"] == "SL_AFTER_TP1" for r in records)
        scenario_sensitivity[scenario] = {
            "closed_including_sl_after_tp1": len(partial_records),
            "total_gross_r": round(scenario_total, 6),
            "expectancy_r": round(scenario_total / len(partial_records), 6) if partial_records else None,
        }
    profit = sum(x for x in gross if x > 0)
    loss = -sum(x for x in gross if x < 0)
    return {
        "signals": len(records),
        "tp2": sum(r["status"] == "TP2" for r in records),
        "sl": sum(r["status"] == "SL" for r in records),
        "sl_after_tp1": sum(r["status"] == "SL_AFTER_TP1" for r in records),
        "ambiguous": sum(r["status"] == "AMBIGUOUS" for r in records),
        "active": sum(r["status"] == "ACTIVE" for r in records),
        "definite_closed": len(definite),
        "gross_total_r": round(sum(gross), 6),
        "gross_expectancy_r": round(sum(gross)/len(gross), 6) if gross else None,
        "gross_profit_factor": round(profit/loss, 6) if loss else ("infinite" if profit else None),
        "max_consecutive_sl": maximum,
        "sl_after_tp1_scenarios_r": SCENARIOS,
        "sl_after_tp1_sensitivity": scenario_sensitivity,
        "fee_bps_per_side": fee_bps,
        "estimated_round_trip_fee_r": round(sum(fees), 6) if fee_bps is not None else None,
        "net_total_r": round(sum(net), 6) if net is not None else None,
        "net_expectancy_r": round(sum(net)/len(net), 6) if net else None,
    }


def build_report(history, fee_bps=None):
    validate(history)
    groups = {}
    for item in history:
        groups.setdefault(str(item["symbol"]), []).append(item)
    return {
        "disclaimer": "Resultados teóricos, no PnL realizado ni backtest de fills. TP2=+2R y SL=-1R brutos. SL_AFTER_TP1 depende de la gestión y se presenta por escenarios.",
        "total": metrics(history, fee_bps),
        "by_symbol": {symbol: metrics(rows, fee_bps) for symbol, rows in sorted(groups.items())},
    }


def markdown(report):
    t = report["total"]
    rows = [
        "# Crypto Signals V1 — auditoría teórica",
        "",
        "> " + report["disclaimer"],
        "",
        "| Métrica | Total |",
        "|---|---:|",
    ]
    for label, key in [
        ("Señales", "signals"), ("TP2", "tp2"), ("SL", "sl"),
        ("SL después de TP1", "sl_after_tp1"), ("Ambiguas", "ambiguous"),
        ("Activas", "active"), ("Cerradas definidas", "definite_closed"),
        ("R bruto total", "gross_total_r"), ("Expectativa bruta (R)", "gross_expectancy_r"),
        ("Factor de beneficio bruto", "gross_profit_factor"), ("Racha máxima de SL", "max_consecutive_sl"),
    ]:
        rows.append("| " + label + " | " + str(t[key]) + " |")
    if t["fee_bps_per_side"] is not None:
        rows.extend([
            "| Comisión por lado (bps) | " + str(t["fee_bps_per_side"]) + " |",
            "| Coste estimado ida/vuelta (R) | " + str(t["estimated_round_trip_fee_r"]) + " |",
            "| R neto estimado | " + str(t["net_total_r"]) + " |",
            "| Expectativa neta estimada (R) | " + str(t["net_expectancy_r"]) + " |",
        ])
    rows.extend(["", "## Escenarios hipotéticos para SL_AFTER_TP1", "", "| Gestión | Impacto individual y sensibilidad total |", "|---|---|"])
    for name, value in SCENARIOS.items():
        sensitivity = t["sl_after_tp1_sensitivity"][name]
        rows.append("| " + name + " | " + format(value, "+.2f") + "R por señal; total " + str(sensitivity["total_gross_r"]) + "R; expectativa " + str(sensitivity["expectancy_r"]) + "R |")
    rows.extend(["", "## Por símbolo", "", "| Símbolo | Señales | TP2 | SL | SL tras TP1 | Ambiguas | Activas | Cerradas | Expectativa bruta (R) |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for symbol, m in report["by_symbol"].items():
        values = [symbol, m["signals"], m["tp2"], m["sl"], m["sl_after_tp1"], m["ambiguous"], m["active"], m["definite_closed"], m["gross_expectancy_r"]]
        rows.append("| " + " | ".join(str(v) for v in values) + " |")
    rows.extend([
        "", "## Interpretación", "",
        "- Solo TP2 (+2R) y SL (-1R) entran en la expectativa principal.",
        "- SL_AFTER_TP1 se excluye de la métrica principal; depende de la gestión aplicada.",
        "- AMBIGUOUS y ACTIVE se excluyen de cerradas.",
        "- Las comisiones solo se estiman si se especifica --fee-bps; es una aproximación por lado sobre el nominal de entrada.",
        "- No se modelan spread, slippage, funding, latencia, fills parciales ni tamaño de posición.",
        "- Una muestra pequeña no demuestra ventaja estadística.", "",
    ])
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description="Auditoría de señales en modo solo lectura")
    parser.add_argument("--history", default="data/signals_history.json")
    parser.add_argument("--fee-bps", type=float, default=None, help="Comisión por lado en puntos básicos")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    if args.fee_bps is not None and (not math.isfinite(args.fee_bps) or args.fee_bps < 0):
        parser.error("--fee-bps debe ser finito y no negativo")
    try:
        history = json.loads(Path(args.history).read_text(encoding="utf-8"))
        report = build_report(history, args.fee_bps)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.format == "json" else markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
