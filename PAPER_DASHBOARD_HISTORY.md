# Historial de snapshots del dashboard paper

Este flujo genera snapshots de valoración del portfolio paper. **No es un historial de operaciones** y no ejecuta órdenes.

El exportador solo lee:
- `data/paper_state.json`
- El archivo opcional de precios de referencia `marks.json`
- El historial anterior indicado con `--history`

El JSON actualizado se escribe únicamente en stdout. El script no crea, reemplaza ni modifica archivos.

## Primer snapshot

Si hay posiciones abiertas, prepara `marks.json` con precios USDT verificados y contemporáneos para cada activo. Si no hay posiciones abiertas, puedes omitir `--marks`.

```bash
python export_legacy_paper_state.py --input data/paper_state.json --marks marks.json > dashboard_history.next.json
```

Revisa el archivo generado antes de conservarlo como historial.

## Añadir un snapshot posterior

Usa el historial anterior como entrada y redirige la salida a un archivo distinto:

```bash
python export_legacy_paper_state.py --input data/paper_state.json --marks marks.json --history dashboard_history.json > dashboard_history.next.json
```

Si no hay posiciones abiertas, omite `--marks` en el comando.

El programa valida el historial existente y exige que el nuevo snapshot tenga una fecha posterior a la última. Si el JSON anterior está dañado, hay IDs duplicados o la fecha no avanza, la exportación se rechaza.

## Conservación segura del historial

1. Conserva intactos `paper_state.json`, `marks.json` y `dashboard_history.json` durante la exportación.
2. Comprueba que `dashboard_history.next.json` contiene todos los snapshots esperados.
3. Solo después de revisarlo, decide manualmente si reemplazas tu archivo de historial anterior por el nuevo.
4. Mantén copias de respaldo si necesitas conservar versiones anteriores.

El exportador nunca reemplaza automáticamente el archivo de historial ni escribe en el estado del simulador.

## Interpretación

Cada ejecución añade una valoración puntual. Para ver una curva histórica hacen falta múltiples snapshots en orden cronológico, con precios de referencia reales y correspondientes al momento de cada captura. Los snapshots no deben confundirse con trades ejecutados ni usarse como prueba de rentabilidad futura.
