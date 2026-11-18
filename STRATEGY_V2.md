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
