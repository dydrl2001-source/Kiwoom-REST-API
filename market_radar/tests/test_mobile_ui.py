import os,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault("DATABASE_URL","")
os.environ.setdefault("DASHBOARD_TOKEN","test")

import mobile_ui

class MobileUISourceTests(unittest.TestCase):
    def test_mobile_is_installable_pwa(self):
        self.assertIn('viewport-fit=cover', mobile_ui.MOBILE_HTML)
        self.assertIn('/mobile/manifest.webmanifest', mobile_ui.MOBILE_HTML)
        self.assertIn('serviceWorker', mobile_ui.MOBILE_HTML)
        self.assertIn('"display":"standalone"', mobile_ui.MOBILE_MANIFEST)

    def test_mobile_uses_existing_authenticated_dashboard_api(self):
        self.assertIn('/api/dashboard', mobile_ui.MOBILE_HTML)
        self.assertIn('x-dashboard-token', mobile_ui.MOBILE_HTML)
        self.assertIn('marketRadarToken', mobile_ui.MOBILE_HTML)
        self.assertNotIn('APP_SECRET', mobile_ui.MOBILE_HTML)
        self.assertNotIn('OPENAI_API_KEY', mobile_ui.MOBILE_HTML)

    def test_mobile_has_core_market_sections(self):
        for label in ('주도 테마','급부상 Top12','관찰 후보 Top5','거래대금 강세','수집 상태'):
            self.assertIn(label, mobile_ui.MOBILE_HTML)

    def test_mobile_has_safe_area_bottom_navigation(self):
        self.assertIn('safe-area-inset-bottom', mobile_ui.MOBILE_HTML)
        self.assertIn('class="nav"', mobile_ui.MOBILE_HTML)

    def test_service_worker_never_caches_api_responses(self):
        self.assertIn('includes("/api/")', mobile_ui.MOBILE_SW)

if __name__=="__main__":
    unittest.main()
