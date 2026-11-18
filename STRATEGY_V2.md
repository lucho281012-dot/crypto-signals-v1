# Crypto Signals V2 — investigación aislada

## Estado

Esta rama es experimental y no sustituye a `paper-trading-v1-2`. La estrategia A y su libro `data/paper_state.json` permanecen intactos.

## Motor inicial

`strategy_v2.py` implementa un motor de señales Spot BUY-only, sin llamadas de red, credenciales, funciones de órdenes ni escrituras al estado de paper trading.

- 4h: régimen direccional con EMA20/EMA50 y ADX.
- 1h: tendencia principal con EMA50/EMA200 y ADX.
- 15m: confirmación con EMA20/EMA50.
- 5m: disparador con EMA20/EMA50, cierre, RSI, MACD y volumen.
- Filtro de volatilidad: ATR como porcentaje del precio.
- Stop inicial: 1.5 ATR.
- Objetivo inicial: 2R.
- Dimensionamiento: riesgo máximo objetivo del 1% de equity, exposición bruta máxima del 95%, comisión estimada del 0.1% por lado y máximo de tres posiciones.

Las velas de temporalidad superior solo se consideran cuando su cierre es anterior o igual al cierre de la vela de señal. El remuestreo de 15m a 1h/4h descarta bloques incompletos.

## Validación y límites

Las pruebas de unidad cubren remuestreo, cierre de temporalidades, causalidad de indicadores, validación OHLC y límites de riesgo/exposición.

El histórico actualmente archivado en la rama base cubre aproximadamente 4 días en 5m y 9 días en 15m. Por eso todavía no es posible afirmar que existe una ventaja estadística ni completar una validación robusta de 6–12 meses. La estrategia no debe usarse con dinero real ni conectarse a ejecución.

## Próximas etapas

1. Conseguir y auditar más histórico público sin credenciales.
2. Implementar backtest de cartera con costes, spread/slippage configurables y ejecución conservadora.
3. Separar cronológicamente entrenamiento, validación y prueba fuera de muestra.
4. Medir win rate, profit factor, expectancy, drawdown, R múltiple y Sharpe.
5. Comparar A y B con los mismos símbolos, velas y costes.
6. Añadir un simulador B con estado independiente solo después de aprobar el backtest y sus pruebas.

No se configura ningún workflow programado de trading en esta rama.


## Backtester V2

`backtest_strategy_v2.py` consumes the archived BTC/ETH/SOL 5m and 15m JSONL files, derives closed 1h/4h candles from complete 15m buckets, and evaluates the V2 multi-timeframe filters. It is a portfolio simulation with one shared cash balance.

- Signals are evaluated only on closed 5m candles and enter at the next contiguous 5m candle open.
- The portfolio-wide aggregate stop-risk budget is capped at 1% of marked equity, including estimated entry/exit fees.
- Gross exposure is capped at 95% of marked equity; maximum three simultaneous positions.
- Default costs: 0.10% fee per side and 5 bps slippage per side; both are configurable.
- If stop and target are both touched in the same candle, stop is assumed first. Gaps fill at the candle open.
- Remaining positions are liquidated at the final close with costs.
- Output is written to `strategy_v2_backtest_report.json`; no paper state or trading workflow is touched.

Run locally with:

```bash
python backtest_strategy_v2.py --data-dir data/market_history
python -m unittest -v test_strategy_v2 test_backtest_strategy_v2
```

The report includes trade-level net PnL, fees, win rate, profit factor, expectancy, return and drawdown. Results are only as representative as the archived sample. The currently available history is short and is not sufficient evidence of a durable trading edge.


## Auditoría de recopilación histórica

El colector incremental `market_history_collector.py` sigue consultando Kraken y ahora valida alineación temporal y OHLCV, deduplica por timestamp y reporta discontinuidades del archivo. Una discontinuidad no demuestra por sí sola que falten datos: el archivo OHLCVT histórico oficial de Kraken omite intervalos en los que no hubo operaciones. El backtest no debe inventar velas para esos intervalos.

Kraken documenta que su endpoint REST OHLC devuelve como máximo las 720 velas más recientes por intervalo. Para ampliar el histórico sin cambiar de exchange, Kraken ofrece un archivo OHLCVT descargable desde el inicio de cada mercado hasta el 30 de septiembre de 2026, dividido en cinco partes de aproximadamente 2 GB cada una; también publica actualizaciones trimestrales. El archivo contiene intervalos de 5 y 15 minutos, entre otros, sin encabezado CSV y sin velas de intervalos sin operaciones. Fuente oficial: https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data

La importación de ese paquete completo no se ha realizado: su tamaño es de varios GB y requiere descargar, verificar checksums, extraer solo los pares y temporalidades necesarios, normalizar timestamps y conciliar la cola posterior al 30-09-2026 con el colector incremental. No se ha añadido ningún proceso automático que descargue varios GB ni que escriba archivos históricos en la rama de producción.
