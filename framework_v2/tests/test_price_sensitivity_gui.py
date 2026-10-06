from __future__ import annotations

from datetime import date, timedelta, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget
from unittest.mock import patch

from framework_v2.price_research import research_bars
from framework_v2.price_sensitivity_panel import PriceSensitivityPanel, _SCENARIO_IDS, _TEXT
from framework_v2.product_ui import ProductWorkbench


def _source_run(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    dates=[]; current=date(2024,1,2)
    while len(dates)<4:
        if current.weekday()<5: dates.append(current.isoformat())
        current+=timedelta(days=1)
    bars=[{"code":"4502","date":day,"open":open_price,"close":close_price,"adjustment_factor":1.0}
        for day,open_price,close_price in zip(dates,(10.0,10.0,11.0,12.0),(10.0,11.0,12.0,13.0))]
    recipe={"count":1,"lookback":2,"cash":1000.0,"fee":0.1,"frequency":"daily","signal_template":"price_momentum"}
    raw=json.dumps({"bars":bars,"recipe":recipe},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
    (folder/"research_inputs.json").write_bytes(raw)
    report=research_bars(bars,recipe); report["input_hash"]=hashlib.sha256(raw).hexdigest()
    canonical=json.dumps(report["order_schedule"],sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    report["order_schedule_hash"]=hashlib.sha256(canonical).hexdigest()
    path=folder/"report.json"; path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    return path


class PriceSensitivityGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_imported_panel_comes_from_this_candidate_checkout(self):
        candidate=Path(__file__).resolve().parents[2]
        import framework_v2.price_sensitivity_panel as panel_module
        self.assertTrue(Path(panel_module.__file__).resolve().is_relative_to(candidate),panel_module.__file__)

    def test_public_ml_extra_declares_supported_lightgbm_and_sklearn(self):
        import tomllib
        candidate=Path(__file__).resolve().parents[2]
        with (candidate/"pyproject.toml").open("rb") as stream:
            extras=tomllib.load(stream)["project"]["optional-dependencies"]
        self.assertIn("lightgbm[scikit-learn]>=4.7,<5",extras["ml"])
        self.assertIn("scikit-learn>=1.9,<2",extras["ml"])
        self.assertTrue(any(item.startswith("catboost>=") for item in extras["ml"]))

    def _wait(self, panel, timeout=45):
        deadline=time.monotonic()+timeout
        while panel.busy and time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(panel.busy,"bounded worker did not finish")

    def test_product_workbench_mounts_panel_on_backtest_results_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("framework_v2.data_connection.load_api_key",return_value=None):
                window=ProductWorkbench(Path(temporary))
            self.assertIsNotNone(window.price_sensitivity_panel)
            self.assertIs(window.price_sensitivity_panel.window(),window)
            self.assertIn(window.price_sensitivity_panel,window.pages[3].parentWidget().findChildren(QWidget))
            report=_source_run(Path(temporary)/"source")
            self.assertTrue(window.price_sensitivity_panel.set_source(report))
            self.assertTrue(window.price_sensitivity_panel.run())
            from PySide6.QtGui import QCloseEvent
            close_event=QCloseEvent(); window.closeEvent(close_event)
            self.assertFalse(close_event.isAccepted())
            self._wait(window.price_sensitivity_panel)
            window.set_language("ja_JP")
            self.assertEqual(window.price_sensitivity_panel.language,"ja_JP")
            window._confirm_unsaved=lambda:True
            window.close(); self.app.processEvents()

    def test_explicit_source_locale_and_actual_three_case_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); report=_source_run(root/"source")
            panel=PriceSensitivityPanel(root/"workspace",parent=None)
            self.assertTrue(panel.set_source(report))
            selected_sha=hashlib.sha256(report.read_bytes()).hexdigest()
            self.assertEqual(panel.source_sha256,selected_sha)
            self.assertTrue(panel.run_button.isEnabled())
            self.assertTrue(panel.run())
            self._wait(panel)
            self.assertIsNotNone(panel.result,panel.status.text())
            self.assertEqual(tuple(row["id"] for row in panel.result["scenarios"]),_SCENARIO_IDS)
            self.assertEqual(panel.table.rowCount(),3)
            self.assertEqual(panel.chart.paths and len(panel.chart.paths),3)
            self.assertIn("report SHA256",panel.logs.text())
            self.assertTrue((panel.job_dir/"request.json").is_file())
            self.assertTrue((panel.job_dir/"launch.json").is_file())
            self.assertTrue((panel.job_dir/"exit.json").is_file())
            for language, expected in (("zh_CN","三个情景均已完成"),("ja_JP","3シナリオが完了"),("en_US","All three scenarios completed")):
                panel.set_language(language)
                self.assertIn(expected,panel.status.text())
                self.assertEqual(panel.table.rowCount(),3)
            self.assertFalse(panel.set_source(root/"missing-report.json"))
            self.assertIsNone(panel.result)
            self.assertEqual(panel.table.rowCount(),0)
            self.assertFalse(panel.run_button.isEnabled())
            panel.deleteLater(); self.app.processEvents()

    def test_source_change_while_worker_runs_discards_stale_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); report=_source_run(root/"source")
            panel=PriceSensitivityPanel(root/"workspace",parent=None)
            self.assertTrue(panel.set_source(report)); self.assertTrue(panel.run())
            panel.set_language("en_US")
            self.assertEqual(panel.status.text(),"Running all three scenarios offline…")
            # Invalidate synchronously before the worker's completion callback can
            # render its report. The subprocess may finish, but its result is stale.
            self.assertFalse(panel.set_source(None))
            self._wait(panel)
            self.assertIsNone(panel.result)
            self.assertEqual(panel.table.rowCount(),0)
            self.assertEqual(panel.status.text(),"The input changed; the previous result was cleared.")
            panel.deleteLater(); self.app.processEvents()

    def test_nav_chart_paints_nonempty_long_series_and_trilingual_legends(self):
        # Deterministic rendering fixture: 1,464 actual points are drawn by the
        # widget; it makes no claim about strategy performance or market data.
        start=date(2017,1,1); scenarios=[]
        for case_index in range(3):
            rows=[]; peak=1.0
            for index in range(1464):
                nav=1.0+0.00005*index+0.012*((index%37)-18)/18 + case_index*0.00001*index
                peak=max(peak,nav)
                rows.append({"at":(start+timedelta(days=index)).isoformat(),"nav":nav,"drawdown":nav/peak-1})
            scenarios.append({"financial_path":{"nav":rows}})
        tmp=tempfile.TemporaryDirectory(); panel=PriceSensitivityPanel(Path(tmp.name),parent=None)
        from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
        if sys.platform.startswith("win"):
            expected_family_prefix = "Microsoft YaHei"
            font_candidates = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
                for name in ("msyh.ttc", "msyhbd.ttc")]
            preferred_families = ("Microsoft YaHei UI", "Microsoft YaHei")
        else:
            expected_family_prefix = "Noto Sans CJK"
            font_candidates = [Path(path) for path in (
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
                "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
            )]
            preferred_families = ("Noto Sans CJK JP", "Noto Sans CJK SC",
                "Noto Sans CJK TC", "Noto Sans CJK KR")
        font_family = next((family for family in preferred_families
            if QFontDatabase.hasFamily(family)), None)
        if font_family is None:
            for font_path in font_candidates:
                if not font_path.is_file():
                    continue
                font_id = QFontDatabase.addApplicationFont(str(font_path))
                if font_id < 0:
                    continue
                font_family = next((family for family in QFontDatabase.applicationFontFamilies(font_id)
                    if family.startswith(expected_family_prefix)), None)
                if font_family:
                    break
        self.assertIsNotNone(font_family,
            f"expected platform CJK font ({expected_family_prefix}); checked {font_candidates}")
        self.assertTrue(font_family.startswith(expected_family_prefix), font_family)
        font=QFont(font_family,8)
        font_metrics=QFontMetrics(font)
        panel.resize(1100,700); panel.chart.resize(1050,300); panel.chart.setFont(font)
        errors=[]; old_hook=sys.excepthook
        evidence_root=Path(os.environ.get("KABUFORGE_TEST_EVIDENCE_ROOT",tmp.name))
        evidence=evidence_root/("sensitivity-paint-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        evidence.mkdir(parents=True,exist_ok=False); screenshots=[]
        try:
            sys.excepthook=lambda *args:errors.append(args)
            for language in ("zh_CN","ja_JP","en_US"):
                panel.set_language(language)
                labels=_TEXT[language]["chart_case"]
                self.assertEqual(len(labels),3)
                unsupported = sorted({char for text in labels for char in text
                    if ord(char) > 127 and not font_metrics.inFontUcs4(ord(char))})
                self.assertEqual(unsupported, [], f"{font_family} lacks {language} legend glyphs")
                self.assertLessEqual(max(font_metrics.horizontalAdvance(text) for text in labels),150)
                panel.chart.set_scenarios(scenarios,labels)
                panel.show(); self.app.processEvents()
                full=panel.grab(); chart_image=panel.chart.grab()
                self.assertFalse(full.isNull()); self.assertFalse(chart_image.isNull())
                for name,image in ((f"{language}-full-panel.png",full),(f"{language}-nav-chart.png",chart_image)):
                    target=evidence/name; self.assertTrue(image.save(str(target))); screenshots.append(str(target.resolve()))
                self.assertEqual(len(panel.chart.paths),3)
                self.assertTrue(all(len(path)==1464 for path in panel.chart.paths))
                self.assertEqual(panel.chart.axis_dates,(scenarios[0]["financial_path"]["nav"][0]["at"],
                    scenarios[0]["financial_path"]["nav"][-1]["at"]))
                self.assertEqual(panel.chart.axis_labels["start_date"]["text"],panel.chart.axis_dates[0])
                self.assertEqual(panel.chart.axis_labels["end_date"]["text"],panel.chart.axis_dates[1])
                for label in panel.chart.axis_labels.values():
                    x,y,width,height=label["rect"]
                    self.assertGreaterEqual(x,0); self.assertGreaterEqual(y,0)
                    self.assertGreater(width,0); self.assertGreater(height,0)
                    self.assertLessEqual(x+width,panel.chart.width())
                    self.assertLessEqual(y+height,panel.chart.height())
            self.assertEqual(errors,[])
            (evidence/"receipt.json").write_text(json.dumps({"result":"rendered","data":"deterministic synthetic rendering fixture; not a finance claim",
                "series_count":3,"points_per_series":1464,"font":"Microsoft YaHei UI 8pt","legend_max_width_px":150,
                "nav_axis_dates":[scenarios[0]["financial_path"]["nav"][0]["at"],scenarios[0]["financial_path"]["nav"][-1]["at"]],
                "screenshots":screenshots},ensure_ascii=False,indent=2),encoding="utf-8")
        finally:
            sys.excepthook=old_hook; panel.close(); panel.deleteLater(); self.app.processEvents(); tmp.cleanup()


if __name__=="__main__": unittest.main()
