# Auditoría de rendimiento de señales

**Corte de datos: 14 de noviembre de 2026**  
**Historial analizado:** `main:data/signals_history.json`  
**SHA del historial:** `3de9e84c104b6f8ed2a110cfd20aab86c20c03d0`

Herramienta de análisis **solo lectura** para `data/signals_history.json`.
No ejecuta órdenes, no consulta exchanges y no modifica el historial ni los
saldos de Paper Trading.

## Resultado del corte actual

| Estado | Cantidad |
|---|---:|
| Total de señales | 76 |
| TP2 | 28 |
| SL | 40 |
| SL_AFTER_TP1 | 6 |
| AMBIGUOUS | 1 |
| ACTIVE | 1 |

La métrica principal incluye únicamente las 68 señales cerradas inequívocas
(`TP2` y `SL`):

| Métrica | Resultado |
|---|---:|
| TP2 | 28 |
| SL | 40 |
| R bruto teórico total | +16R |
| Expectativa bruta | +0.2353R por señal |
| Factor de beneficio bruto | 1.4000 |

Supuestos de la métrica principal: cada TP2 equivale a +2R y cada SL a -1R.
No representa PnL realizado ni demuestra por sí sola una ventaja estadística.

## Resultados por símbolo

| Símbolo | Señales | TP2 | SL | SL_AFTER_TP1 | Ambiguas | Activas | Cerradas definidas | R bruto | Expectativa |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC/USDT | 29 | 10 | 16 | 3 | 0 | 0 | 26 | +4R | +0.1538R |
| ETH/USDT | 24 | 8 | 12 | 3 | 1 | 0 | 20 | +4R | +0.2000R |
| SOL/USDT | 23 | 10 | 12 | 0 | 0 | 1 | 22 | +8R | +0.3636R |

## Sensibilidad de SL_AFTER_TP1

Hay 74 señales cerradas si se incluyen las 6 `SL_AFTER_TP1` y se excluyen las ambiguas y activas.
Como su resultado depende de la gestión aplicada, se muestran escenarios hipotéticos:

| Gestión hipotética | R total | Expectativa |
|---|---:|---:|
| Sin parcial | +10R | +0.1351R |
| 50% TP1 / 50% break-even | +19R | +0.2568R |
| 50% TP1 / 50% stop original | +16R | +0.2162R |

Estos escenarios no afirman qué gestión se ejecutó realmente.

## Uso

```bash
python audit_signal_performance.py
python audit_signal_performance.py --format json
python audit_signal_performance.py --fee-bps 10
```

`--fee-bps` representa la comisión estimada **por lado**, en puntos básicos.
No se aplica comisión por defecto porque la tarifa real puede variar. El coste
ida/vuelta es una aproximación sobre el nominal de entrada.

## Supuestos y validaciones

- `TP2`: +2R bruto teórico.
- `SL`: -1R bruto teórico.
- `SL_AFTER_TP1`: se excluye de la expectativa principal y se muestran escenarios.
- `AMBIGUOUS` y `ACTIVE`: excluidos de resultados cerrados.
- R se calcula con la distancia entre entrada y stop.
- Se validan campos, IDs duplicados, dirección y coherencia de niveles 1R/2R.
- Las rachas de SL se calculan por símbolo para no mezclar activos distintos.

En este corte, la validación del historial encontró **0 errores** de IDs duplicados o niveles incompatibles.

## Limitaciones

No es PnL realizado ni un backtest de ejecución. No simula spread, slippage,
funding, latencia, fills parciales, tamaño de posición ni gestión real. Las
comisiones son aproximadas y solo se calculan si se proporcionan. La muestra
sigue siendo pequeña; los resultados son descriptivos y no justifican por sí
solos pasar a trading real.
