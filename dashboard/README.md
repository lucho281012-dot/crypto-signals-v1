# Dashboard UI

La página `index.html` es una maqueta estática y adaptable a móviles.

## Estado actual

- Todos los números son ficticios y se muestran como DEMO.
- No consume APIs, archivos JSON, almacenamiento local ni datos del exchange.
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

La integración deberá ser estrictamente de lectura, validar el esquema y los valores finitos, y mantener separada la fuente de historial del archivo operativo `paper_state.json`. Esta documentación no activa esa integración.

## Vista en Android

Para probar el diseño localmente, abre `index.html` en un navegador moderno. La publicación web (por ejemplo, GitHub Pages) requiere una decisión y configuración explícitas del propietario del repositorio; no se activa desde esta rama.
