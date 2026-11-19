# Auditoría de calidad de señales — estado inicial

## Alcance
Esta auditoría observa el motor actual del simulador Spot. No cambia reglas de entrada, ejecución, stops, take-profit, workflow activo ni el estado persistido.

## Reglas actuales observadas
- Activos: BTC/USDT, ETH/USDT y SOL/USDT.
- Temporalidades: 5 minutos para condiciones de entrada y 15 minutos para confirmar tendencia.
- Requiere al menos 200 velas por temporalidad.
- Indicadores: EMA 20, EMA 200, RSI 14, MACD (12, 26, 9), volumen medio 20 y ATR 14.
- BUY cuando al menos 4 de 5 condiciones de 5m se cumplen y EMA20 > EMA200 en 15m:
  1. EMA20 > EMA200.
  2. RSI > 50.
  3. MACD > línea de señal.
  4. Volumen > media de volumen 20.
  5. Cierre > EMA20.
- Stop de referencia: 1.2 ATR; objetivo: 2 veces la distancia entre entrada y stop.
- Las decisiones del motor seleccionan la vela cerrada (-2), no la vela en formación (-1).

## Hallazgo de implementación a revisar
El motor devuelve el cierre de la vela confirmada como `entry`, pero el bot coloca el precio de entrada en la apertura de la vela más reciente (-1). Esto equivale a simular entrada en la apertura posterior a la confirmación y puede ser una aproximación razonable; se debe medir el gap/deslizamiento entre ambos precios y mantener coherencia entre precio de entrada, stop, objetivo y riesgo efectivo. No se debe reemplazar por el cierre confirmado sin justificar el modelo de ejecución.

## Qué falta antes de afirmar precisión
1. Backtest cronológico sin look-ahead, con datos OHLCV completos y limpios para cada activo y timeframe.
2. Separación temporal entre entrenamiento/ajuste, validación y prueba final fuera de muestra.
3. Comisiones, spread, slippage y latencia modelados conservadoramente.
4. Evitar sobreajuste al probar parámetros; conservar un conjunto final intocable.
5. Medir por activo y régimen: número de operaciones, win rate, expectancy neta, profit factor, retorno, drawdown máximo, rachas, exposición y sensibilidad a costes.
6. Comparar contra buy-and-hold y una referencia simple.
7. Paper trading prospectivo suficiente antes de cualquier decisión sobre dinero real.

## Criterios operativos recomendados
- No emitir una señal si falta una vela, hay datos no finitos, timestamps desalineados o el mercado no se puede valorar correctamente.
- Preferir WAIT/SIN SEÑAL cuando la evidencia sea insuficiente.
- No presentar win rate como garantía ni usar un único porcentaje para declarar una estrategia rentable.
- Mantener ejecución real deshabilitada hasta aprobar pruebas, revisión y autorización explícita del usuario.

## Seguridad
Esta rama es aislada. No activa órdenes reales, no usa credenciales privadas y no modifica `paper-trading-v1-2` ni `data/paper_state.json`.
