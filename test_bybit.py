
import sys
import time
import requests

from datetime import datetime, timezone


BASE_URL = "https://api.bybit.com/v5/market/kline"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
]

TIMEFRAMES = [
    "5",
    "15",
]

TIMEOUT = 20
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": "CryptoSignals-PaperTrading/1.0",
    "Accept": "application/json",
}


def print_http_error(response, symbol, interval):
    print("\n" + "=" * 55)
    print("ERROR HTTP EN BYBIT")
    print("=" * 55)

    print(f"Símbolo: {symbol}")
    print(f"Temporalidad: {interval} minutos")
    print(f"Código HTTP: {response.status_code}")
    print(f"URL: {response.url}")

    print("\nRespuesta del servidor:")
    print(response.text[:2000])

    print("\nHeaders relevantes:")

    for header in [
        "Server",
        "Content-Type",
        "Retry-After",
        "CF-Ray",
    ]:
        value = response.headers.get(header)

        if value:
            print(f"{header}: {value}")

    print("=" * 55)


def test_market_data(session, symbol, interval):

    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "limit": 3,
    }

    print(f"\nConsultando {symbol} - {interval} minutos...")

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = session.get(
                BASE_URL,
                params=params,
                timeout=TIMEOUT,
            )

            if response.status_code != 200:

                print_http_error(
                    response,
                    symbol,
                    interval,
                )

                # No repetir automáticamente un HTTP 403.
                if response.status_code == 403:
                    raise RuntimeError(
                        "Bybit rechazó la solicitud con HTTP 403. "
                        "Se necesita revisar la respuesta del servidor."
                    )

                # Reintentar únicamente errores temporales.
                if response.status_code in [
                    429, 500, 502, 503, 504
                ] and attempt < MAX_RETRIES:

                    print(
                        f"Error temporal. Reintento "
                        f"{attempt}/{MAX_RETRIES}..."
                    )

                    time.sleep(attempt * 3)
                    continue

                response.raise_for_status()

            try:
                data = response.json()

            except ValueError:
                print("Bybit no devolvió una respuesta JSON válida.")
                print(response.text[:2000])

                raise RuntimeError(
                    "Respuesta JSON inválida."
                )

            if data.get("retCode") != 0:
                raise RuntimeError(
                    f"Error de Bybit: "
                    f"{data.get('retCode')} - "
                    f"{data.get('retMsg')}"
                )

            candles = data.get("result", {}).get("list", [])

            if not candles:
                raise RuntimeError(
                    f"Bybit no devolvió velas para {symbol}."
                )

            # Orden cronológico: de la más antigua a la más reciente.
            candles = sorted(
                candles,
                key=lambda candle: int(candle[0]),
            )

            print("\nCONEXIÓN CORRECTA")
            print(f"Símbolo: {symbol}")
            print(f"Temporalidad: {interval} minutos")
            print(f"Velas recibidas: {len(candles)}")

            for candle in candles:

                timestamp = datetime.fromtimestamp(
                    int(candle[0]) / 1000,
                    timezone.utc,
                )

                print(
                    f"{timestamp:%Y-%m-%d %H:%M UTC} | "
                    f"O: {candle[1]} | "
                    f"H: {candle[2]} | "
                    f"L: {candle[3]} | "
                    f"C: {candle[4]} | "
                    f"V: {candle[5]}"
                )

            return True

        except requests.exceptions.Timeout:
            print(
                f"Tiempo de espera agotado. "
                f"Intento {attempt}/{MAX_RETRIES}."
            )

            if attempt == MAX_RETRIES:
                raise

            time.sleep(attempt * 3)

        except requests.exceptions.ConnectionError:
            print(
                f"Error de conexión. "
                f"Intento {attempt}/{MAX_RETRIES}."
            )

            if attempt == MAX_RETRIES:
                raise

            time.sleep(attempt * 3)

    return False


def main():

    print("=" * 55)
    print("CRYPTO SIGNALS - PRUEBA DE CONEXIÓN BYBIT")
    print("=" * 55)

    session = requests.Session()
    session.headers.update(HEADERS)

    successful = 0
    failed = 0

    try:

        for symbol in SYMBOLS:

            for timeframe in TIMEFRAMES:

                try:
                    if test_market_data(
                        session,
                        symbol,
                        timeframe,
                    ):
                        successful += 1

                except Exception as error:
                    failed += 1

                    print(
                        f"\nFALLO: {symbol} "
                        f"{timeframe} minutos"
                    )

                    print(f"Detalle: {error}")

                    # Un 403 indica que debemos investigar
                    # el acceso antes de continuar.
                    if "HTTP 403" in str(error):
                        print(
                            "\nPrueba detenida por rechazo HTTP 403."
                        )
                        raise

    finally:
        session.close()

    print("\n" + "=" * 55)
    print("RESUMEN DE LA PRUEBA")
    print("=" * 55)

    print(f"Consultas exitosas: {successful}")
    print(f"Consultas fallidas: {failed}")

    if successful == 6 and failed == 0:

        print("\nPRUEBA COMPLETADA CORRECTAMENTE")

    else:

        print("\nPRUEBA NO COMPLETADA")

        sys.exit(1)


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("\nERROR FINAL:")
        print(error)

        sys.exit(1)
