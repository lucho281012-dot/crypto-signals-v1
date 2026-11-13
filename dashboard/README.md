# Dashboard UI

La página `index.html` es una maqueta estática y adaptable a móviles.

## Estado actual

- Todos los números son ficticios y se muestran como DEMO.
- No consume APIs ni datos del exchange. Permite importar manualmente un archivo JSON local de historial.
- No se conecta a `paper_state.json`, al bot ni a la cuenta paper.
- No ejecuta operaciones ni tiene credenciales.
- El diseño se adapta a pantallas pequeñas; la tabla de snapshots permite desplazamiento horizontal.

## Contrato previsto para la futura integración de solo lectura

La fuente futura será el resultado validado de `build_report_dashboard_model(history)`, no el estado operativo del bot. La vista podrá recibir, cuando se autorice esa fase, estas secciones:

- `summary`: resumen de snapshots y evolución.
- `latest_metrics`: equity, cash, valor de mercado, P&L y retorno.
- `equity_drawdown`: serie y drawdown máximo.
- `latest_assets`: valor y peso de cada activo.
- `charts`: series históricas ya validadas.
- `snapshot_count`: número de snapshots incluidos.

La importación actual es estrictamente de lectura y trabaja solo con el archivo seleccionado por el usuario. No accede a `paper_state.json`, al bot ni a otros archivos del dispositivo. Los datos viven únicamente en memoria mientras la página está abierta. La interfaz de importación no realiza escritura ni transmisión de datos.

## Archivo de prueba

El archivo `sample_history_demo.json` contiene cuatro snapshots completamente ficticios para probar la importación manual. El test automatizado valida su estructura y las métricas finales esperadas.

Puedes descargarlo desde la rama de trabajo:
[Descargar historial DEMO JSON](https://raw.githubusercontent.com/lucho281012-dot/crypto-signals-v1/paper-report-dashboard-ui/dashboard/sample_history_demo.json)

No contiene operaciones reales ni datos del simulador.

## Vista en Android

Para probar el diseño localmente, abre `index.html` en un navegador moderno. La publicación web (por ejemplo, GitHub Pages) requiere una decisión y configuración explícitas del propietario del repositorio; no se activa desde esta rama.
