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
