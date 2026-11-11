
import sys
import time
import requests

BASE_URL = "https://www.okx.com/api/v5/market/candles"

SYMBOLS = [
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
]

TIMEFRAMES = ["5m", "15m"]
MIN_CANDLES = 210

session = requests.Session()
session.headers.update({
    "User-Agent": "Crypto-Signals-Test/1.0"
})


def test_candles(symbol, timeframe):
    params = {
        "instId": symbol,
        "bar": timeframe,
        "limit": "300",
    }

    response = session.get(
        BASE_URL,
        params=params,
        timeout=20
    )

    response.raise_for_status()
    result = response.json()

    if result.get("code") != "0":
        raise RuntimeError(
            f"OKX error: {result.get('code')} - {result.get('msg')}"
        )

    rows = result.get("data", [])

    # OKX devuelve las velas más recientes primero.
    # El último campo indica si la vela está cerrada:
    # 0 = abierta, 1 = cerrada.
    closed = [
        row for row in rows
        if len(row) >= 9 and row[8] == "1"
    ]

    closed.sort(key=lambda row: int(row[0]))

    if len(closed) < MIN_CANDLES:
        raise RuntimeError(
            f"Datos insuficientes: {len(closed)} velas cerradas"
        )

    for row in closed:
        values = [float(row[i]) for i in range(1, 7)]

        if not all(v >= 0 for v in values):
            raise RuntimeError("Se encontraron valores inválidos")

        if any(float(row[i]) <= 0 for i in range(1, 5)):
            raise RuntimeError("Precio OHLC inválido")

    print(
        f"OK: {symbol} | {timeframe} | "
        f"{len(closed)} velas cerradas"
    )

    print(
        f"Última vela: {closed[-1][0]} | "
        f"Cierre: {closed[-1][4]} | "
        f"Volumen base: {closed[-1][6]}"
    )


def main():
    print("=" * 55)
    print("CRYPTO SIGNALS - PRUEBA DE CONEXIÓN OKX")
    print("=" * 55)

    failures = []

    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            print(f"\nConsultando {symbol} - {timeframe}...")

            try:
                test_candles(symbol, timeframe)
            except Exception as exc:
                print(f"ERROR: {exc}")
                failures.append((symbol, timeframe, str(exc)))

            time.sleep(0.5)

    print("\n" + "=" * 55)

    if failures:
        print(f"PRUEBA FALLIDA: {len(failures)} consulta(s)")
        for symbol, timeframe, error in failures:
            print(f"- {symbol} {timeframe}: {error}")
        sys.exit(1)

    print("PRUEBA COMPLETADA CORRECTAMENTE")
    print("Las seis consultas tienen suficientes velas cerradas.")


if __name__ == "__main__":
    main()
