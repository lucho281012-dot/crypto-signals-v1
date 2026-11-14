# Auditoría de rendimiento de señales

Herramienta de análisis **solo lectura** para `data/signals_history.json`.
No ejecuta órdenes, no consulta exchanges y no modifica el historial ni los
saldos de Paper Trading.

## Uso

```bash
python audit_signal_performance.py
python audit_signal_performance.py --format json
python audit_signal_performance.py --fee-bps 10
```

`--fee-bps` representa la comisión estimada **por lado**, en puntos básicos.
No se aplica comisión por defecto porque la tarifa real puede variar. El coste
ida/vuelta es una aproximación sobre el nominal de entrada.

## Supuestos

- `TP2`: +2R bruto teórico.
- `SL`: -1R bruto teórico.
- `SL_AFTER_TP1`: se excluye de la expectativa principal y se muestran escenarios:
  - Sin parcial: -1R.
  - 50% cerrado en TP1 y 50% en break-even: +0.5R.
  - 50% cerrado en TP1 y 50% en stop original: 0R.
- `AMBIGUOUS` y `ACTIVE`: excluidos de resultados cerrados.

R se calcula con la distancia entre entrada y stop. La herramienta valida los
campos, IDs duplicados, dirección y coherencia de niveles 1R/2R.

## Limitaciones

No es PnL realizado ni un backtest de ejecución. No simula spread, slippage,
funding, latencia, fills parciales, tamaño de posición ni gestión real. Las
comisiones son aproximadas y solo se calculan si se proporcionan. Una muestra
pequeña no demuestra una ventaja estadística.
