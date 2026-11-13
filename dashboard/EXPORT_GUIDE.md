# Exportar historial Paper para el dashboard

Este puente es manual y de solo lectura. Convierte un archivo dedicado de
historial de reportes Paper al JSON que acepta el dashboard móvil.

## Formato de intercambio

El formato canónico es la lista de snapshots con schema_version 1 producida por
paper_report_history.serialize_report_history(history). Es el mismo formato
que valida el importador de dashboard/index.html. El modelo agregado de
paper_report_dashboard.build_report_dashboard_model(history) es para preparar
datos de presentación; no es el archivo que se importa en la interfaz.

## Exportación

Desde la raíz del repositorio, ejecuta:

    python export_paper_dashboard_history.py --input ruta/al/paper_report_history.json > dashboard_history.json

Después, transfiere dashboard_history.json al teléfono e impórtalo con el
selector de historial JSON del dashboard.

## Límites de seguridad

- La entrada debe ser un archivo dedicado de historial de reportes, no paper_state.json.
- El comando valida el historial antes de imprimirlo.
- Solo escribe el JSON por salida estándar; no crea ni modifica archivos.
- No lee datos de exchanges, no inicia el bot y no ejecuta operaciones.
- No programa exportaciones automáticas ni integra este puente al simulador.
- La exportación contiene solo los snapshots ya existentes; no genera datos
  nuevos ni toma snapshots automáticamente.

La rama de trabajo no debe fusionarse ni conectarse al simulador hasta revisar
las pruebas y autorizar explícitamente la siguiente fase.
