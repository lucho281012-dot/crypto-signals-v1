from pathlib import Path
import unittest


class PaperDashboardUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).parent / "dashboard" / "index.html").read_text(
            encoding="utf-8"
        )

    def test_demo_data_is_explicitly_labeled(self):
        self.assertIn("DEMO · DATOS FICTICIOS", self.html)
        self.assertIn("cifras y operaciones de esta pantalla son inventadas", self.html)
        self.assertIn("No representan el saldo real del simulador", self.html)

    def test_dashboard_sections_are_present(self):
        for label in (
            "Equity total",
            "P&amp;L total",
            "Drawdown máximo",
            "Evolución del equity",
            "Distribución de activos",
            "Últimos snapshots",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.html)

    def test_supported_assets_are_present(self):
        for asset in ("BTC", "ETH", "SOL"):
            with self.subTest(asset=asset):
                self.assertIn(asset, self.html)

    def test_page_is_responsive_and_accessible(self):
        self.assertIn('name="viewport"', self.html)
        self.assertIn("@media(max-width:520px)", self.html)
        self.assertIn("overflow-x:auto", self.html)
        self.assertIn("mobile-hint", self.html)
        self.assertIn('aria-label="Tabla desplazable de snapshots"', self.html)
        self.assertIn('role="img"', self.html)
        self.assertIn('lang="es"', self.html)

    def test_local_history_import_is_available_and_read_only(self):
        for token in (
            'id="history-file"',
            'type="file"',
            'accept=".json,application/json"',
            'role="status"',
            "file.text()",
            "JSON.parse",
            "MAX_BYTES = 5 * 1024 * 1024",
            "MAX_SNAPSHOTS = 10000",
            "schema_version !== 1",
            "estrictamente creciente",
            "replaceChildren()",
            "HISTORIAL IMPORTADO",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.html)

    def test_import_validates_numeric_metrics_and_snapshot_order(self):
        self.assertIn('required = ["equity_usdt","cash_usdt","market_value_usdt","total_pnl_usdt","total_return_pct"]', self.html)
        self.assertIn("Number.isFinite(n)", self.html)
        self.assertIn("time <= previous", self.html)
        self.assertIn("ids.has(snapshot.snapshot_id)", self.html)

    def test_import_updates_dashboard_metrics_and_assets(self):
        for token in (
            'setText("equity"',
            'setText("pnl"',
            'setText("drawdown"',
            'setText("cash-value"',
            'setText("market-value"',
            'document.querySelector(".asset-list")',
            'document.querySelector(".table-scroll tbody")',
            'svg.querySelector(".line")',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.html)

    def test_import_errors_keep_demo_data_and_report_status(self):
        self.assertIn("Se conservan los datos que ya estaban cargados", self.html)
        self.assertIn('status.textContent = "No se pudo importar:', self.html)
        self.assertIn('input.value = "";', self.html)

    def test_ui_has_no_network_or_persistence_code(self):
        forbidden = (
            "fetch(", "XMLHttpRequest", "WebSocket", "localStorage",
            "sessionStorage", "indexedDB", "ccxt", "api.binance.com",
            "paper_state.json", "paper_bot.py",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.html)


if __name__ == "__main__":
    unittest.main()
