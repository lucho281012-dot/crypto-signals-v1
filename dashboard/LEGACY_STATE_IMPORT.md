# Exportar el estado legacy al dashboard (solo lectura)

El adaptador `export_legacy_paper_state.py` lee una copia local de `data/paper_state.json` y, si hay posiciones abiertas, un archivo de precios de referencia separado. Emite un único snapshot JSON por stdout para importarlo en `dashboard/index.html`.

## Preparación

Crea un archivo local `marks.json` con el precio USDT de cada activo que tenga una posición abierta. Las claves son el activo base, por ejemplo:

```json
{
  "BTC": "65000.00",
  "ETH": "3200.00"
}
```

Los precios del ejemplo son ilustrativos: reemplázalos por cotizaciones verificadas correspondientes al momento de la valoración. No se descargan precios ni se consulta ningún exchange.

## Exportación

Desde la raíz del repositorio:

```bash
python export_legacy_paper_state.py --input data/paper_state.json --marks marks.json > dashboard_history.json
```

Si no hay posiciones abiertas, `--marks` se puede omitir. Abre el dashboard, selecciona `dashboard_history.json` y se cargarán las métricas.

## Límites de seguridad

- El exportador solo lee el archivo de estado y el archivo de precios.
- No importa `paper_trading.py` ni `paper_bot.py`.
- No modifica ni guarda `paper_state.json`, posiciones, efectivo o historial.
- No consulta redes, APIs ni exchanges.
- Rechaza entradas cuyo nombre no sea exactamente `paper_state.json`.
- Un snapshot representa una valoración puntual; para crear una curva histórica hay que exportar snapshots sucesivos con sus precios de referencia y conservarlos en orden cronológico.
- Los datos de precios deben ser actuales y correctos. Sin ellos, el exportador rechaza posiciones abiertas en lugar de inventar su valor.
