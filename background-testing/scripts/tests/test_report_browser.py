"""Optional real-browser navigation check; never installs a browser or touches live apps."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

SKILL=Path(__file__).resolve().parents[2]
EDGE=Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
AVAILABLE=importlib.util.find_spec('playwright') is not None and EDGE.is_file()


@unittest.skipUnless(AVAILABLE,'Optional Playwright + local Edge are unavailable; browser checks not run.')
class ReportBrowserTests(unittest.TestCase):
    def test_external_case_link_and_filtered_hash_navigation(self):
        from playwright.sync_api import sync_playwright
        spec=importlib.util.spec_from_file_location('browser_report',SKILL/'scripts'/'report.py')
        report=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(report)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'中文 report'
            shutil.copytree(SKILL/'assets'/'report-example',root)
            self.assertEqual(0,report.main([str(root/'run.json')]))
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=str(EDGE),headless=True)
                try:
                    page=browser.new_page()
                    page.goto((root/'report.html').as_uri()+'#case-UI-01')
                    self.assertTrue(page.locator('#case-UI-01').evaluate('(e)=>e.open'))
                    page.select_option('#status','Failed')
                    self.assertEqual(1,page.locator('.case:visible').count())
                    self.assertFalse(page.locator('#case-DIAG-01').is_visible())
                    page.evaluate('location.hash="#case-DIAG-01"')
                    page.wait_for_function('document.getElementById("case-DIAG-01").open')
                    self.assertTrue(page.locator('#case-DIAG-01').is_visible())
                    self.assertEqual('',page.locator('#status').input_value())
                    self.assertIn('4 / 4',page.locator('#shown').inner_text())
                finally:
                    browser.close()


if __name__=='__main__':
    unittest.main()
