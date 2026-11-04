# Crypto Signals V1.1 — GitHub Actions

Bot de alertas LONG/SHORT para BTC, ETH y SOL. Solo usa datos públicos de Binance USD-M Futures; no ejecuta órdenes ni necesita claves de Binance.

## Limitación importante
GitHub Actions no es un servidor permanente. La programación mínima es cada 5 minutos, pero las ejecuciones pueden retrasarse o perderse en periodos de carga. No es adecuado para scalping que requiera ejecución exacta.

En repositorios públicos, los runners estándar de GitHub Actions son gratuitos y el código es visible para todos. Los secretos configurados en Settings no se publican. En repositorios privados, el plan Free incluye 2.000 minutos/mes; una tarea cada 5 minutos podría superar la cuota. No habilites pagos adicionales.

## Preparación de Telegram
1. En Telegram abre @BotFather, envía /newbot y crea el bot.
2. Guarda el token en privado.
3. Abre el nuevo bot y envíale /start.
4. Obtén el chat ID visitando `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` y leyendo `message.chat.id`.
5. No publiques el token.

## Crear repositorio
1. Regístrate en https://github.com/signup y confirma el correo.
2. Pulsa New repository y nómbralo `crypto-signals-v1`.
3. Elige Public si aceptas que el código sea visible y quieres Actions gratis sin consumir minutos. O Private, pero vigila el límite mensual.
4. Crea el repositorio.

## Subir archivos
Descomprime el ZIP y en GitHub usa Add file → Upload files. Sube `signal_once.py`, `requirements.txt` y la carpeta `.github/workflows/signals.yml`. Puedes subir también README.md. No subas tokens, archivos .env ni credenciales.

## Guardar secretos
En el repositorio: Settings → Secrets and variables → Actions → New repository secret.
Crea:
- `TELEGRAM_BOT_TOKEN`: token de BotFather.
- `TELEGRAM_CHAT_ID`: tu chat ID numérico.

## Activar
1. Abre Actions y habilita los workflows si GitHub lo solicita.
2. Selecciona Crypto Signals V1.1.
3. Pulsa Run workflow para probar manualmente.
4. Revisa los pasos de la ejecución. Si no hay señal, no se envía mensaje; eso es normal.
5. El horario intentará ejecutarlo cada 5 minutos.

El archivo `data/state.json` se guarda en el repositorio para evitar procesar repetidamente la misma vela. En un repo público será visible, pero no contiene secretos.

## Estrategia
Vela cerrada de 5m, confirmación de tendencia 15m, EMA20/EMA200, RSI14, MACD, ATR14 y volumen SMA20. Requiere 4/5 filtros y confirmación 15m. Stop = 1.2 ATR; TP1 = 1R; TP2 = 2R.

## Limitaciones
No se garantiza 90% de aciertos. Esta versión no monitorea el resultado posterior ni calcula win rate. La entrada es el cierre de la vela y el precio puede cambiar antes de recibir la alerta. No incluye spread, funding, slippage ni comisiones reales. Prueba primero sin operar y evalúa al menos 100 señales.
