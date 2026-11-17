# Crypto Signals — Paper Trading Spot

Esta rama ejecuta un simulador de trading **Spot** para BTC/USDT, ETH/USDT y SOL/USDT usando datos públicos de Kraken. No envía órdenes reales ni necesita claves privadas de exchange.

## Funcionamiento

- Datos de mercado: Kraken mediante CCXT.
- Pares: BTC/USDT, ETH/USDT y SOL/USDT.
- Señal: BUY únicamente (sin posiciones cortas).
- Marco de entrada: velas de 5 minutos cerradas.
- Confirmación de tendencia: velas de 15 minutos cerradas.
- Indicadores: EMA20, EMA200, RSI14, MACD, ATR14 y volumen SMA20.
- Entrada simulada: apertura de la vela siguiente a la señal.
- Stop: 1.2 ATR; objetivo: 2R.
- Comisión simulada: 0.1% por lado.
- Saldo inicial de referencia: 100 USDT; riesgo objetivo por operación: 1% del saldo inicial, sujeto a límites de saldo y exposición.

## Automatización

GitHub Actions intenta ejecutar el simulador cada cinco minutos. Los horarios pueden retrasarse o perderse; no es un motor de ejecución en tiempo real y no es adecuado para scalping que requiera precisión temporal.

En cada ejecución se ejecutan primero las pruebas unitarias, luego el simulador y el informe por activo. El estado se guarda en `data/paper_state.json`.

## Estadísticas

`python paper_report.py` muestra, por separado para cada símbolo:
- resultados de todo el historial;
- resultados desde la fecha `baseline_metadata.created_at`.

Las operaciones anteriores a la fecha base no se borran: quedan visibles en el historial completo, pero no contaminan la evaluación posterior al baseline. El informe usa `opened_at` para clasificar cada operación.

## Pruebas locales

Instala dependencias y ejecuta:

```bash
pip install -r requirements.txt
python -m unittest discover -v
python paper_report.py
```

## Limitaciones y seguridad

- Los resultados son simulados; no equivalen a ejecuciones reales.
- El modelo no incorpora spread ni slippage variable; la comisión fija no necesariamente representa la tarifa real.
- La entrada se aproxima usando la apertura de la vela siguiente y puede diferir del precio disponible tras retrasos.
- Si stop y objetivo aparecen dentro de la misma vela, se aplica la hipótesis conservadora de stop primero.
- La reconstrucción de huecos depende del histórico público disponible en Kraken.
- Una muestra pequeña no demuestra rentabilidad. Mantener la prueba en paper trading y reunir al menos 100 operaciones evaluables por activo antes de sacar conclusiones.
- No se garantiza ningún porcentaje de acierto ni beneficio.
