"""End-to-end GUI workflows with isolated fixtures and no credentials/network."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import tempfile,time,json,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from framework_v2.product_ui import ProductWorkbench
from framework_v2.guided_strategy import parse_sentence
from framework_v2.help_viewer import HelpDialog,manual_html
from framework_v2.manual_content import CHAPTERS
from framework_v2.price_research import research_bars

class ProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        with patch("framework_v2.data_connection.load_api_key",return_value=None): self.window=ProductWorkbench(self.root)
        self.window.show(); self.app.processEvents()
    def tearDown(self):
        if self.window.jobs.busy: self.window.jobs.cancel(); self.wait_job()
        self.window.document._dirty=False; self.window.close(); self.app.processEvents(); self.tmp.cleanup()
    def wait_job(self):
        deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(.01)
            if not self.window.jobs.busy:
                self.app.processEvents()
                if not self.window.jobs.busy: break
        self.assertFalse(self.window.jobs.busy)
        return self.window.jobs.jobs[-1]
    def test_guided_demo_language_preserves_fields_and_history(self):
        w=self.window; w.strategy_name.setText("三语测试")
        w.sentence.setText("每周选3只股票，等权"); self.assertTrue(w.parse_input())
        w.set_language("en_US"); self.assertEqual(w.holding_count.value(),3)
        self.assertEqual(w.strategy_name.text(),"三语测试"); self.assertEqual(w.nav.item(1).text(),"My strategies")
        self.assertTrue(w.create_strategy()); self.assertEqual(self.wait_job()["status"],"COMPLETED")
        strategy=json.loads((w.run_path.parent/"strategy.json").read_text(encoding="utf-8"))
        self.assertEqual(strategy["portfolio"]["parameters"]["top_n"],3)
        self.assertEqual(strategy["rebalance"]["frequency"],"weekly")
        w.set_language("ja_JP"); self.assertEqual(w.nav.item(1).text(),"マイ戦略")
        self.assertTrue(w.run_guided()); self.assertEqual(self.wait_job()["status"],"COMPLETED")
        self.assertIsNotNone(w.report); self.assertTrue(w.report["nav"])
        self.assertFalse(w.advanced_editor.isVisible())
        self.assertGreater(w.library.count(),0)
        self.assertTrue(w.open_saved_strategy()); self.assertEqual(w.guide_recipe["count"],3)
        w.cash.setValue(3000000); self.assertFalse(w.guided_run.isEnabled())
    def test_help_search_links_and_locale(self):
        h=HelpDialog("en_US",self.window); h.show(); self.app.processEvents()
        h.search.setText("Credential Manager"); self.assertEqual(h.contents.count(),1)
        h._select(h.contents.item(0)); self.assertEqual(h.chapter,"connect")
        self.assertTrue(h.find_match()); h.set_language("ja_JP"); self.assertEqual(h.chapter,"connect")
        h.search.setText(""); self.assertEqual(h.contents.count(),len(CHAPTERS["ja_JP"]))
        from PySide6.QtCore import QUrl
        h._anchor(QUrl("#paper")); self.assertEqual(h.chapter,"paper")
        for locale,chapters in CHAPTERS.items():
            html=manual_html(locale)
            for key,*_ in chapters: self.assertIn(f'name="{key}"',html)
        h.close()
    def test_sentence_rejects_unhandled_and_ambiguous(self):
        for text in ("Select 5 stocks monthly, equal weight", "毎月5銘柄を均等配分", "每月选5只股票，等权"):
            self.assertEqual(parse_sentence(text)["count"],5)
        for text in ("每月选5只股票，等权，止损10%", "select 5 or 20 stocks monthly", "buy everything"):
            with self.assertRaises(ValueError): parse_sentence(text)
    def test_layout_and_no_list_forced_linebreak(self):
        w=self.window
        self.assertFalse(w.windowIcon().isNull()); self.assertTrue(w.brand_logo.renderer().isValid())
        from framework_v2.brand_theme import DARK
        self.assertEqual(DARK["brand"],"#E65324"); self.assertEqual(DARK["primary-bg"],"#FF936E")
        for locale in CHAPTERS:
            w.set_language(locale); w.resize(900,720); self.app.processEvents()
            self.assertLessEqual(w.minimumSizeHint().width(),1000)
            self.assertFalse(w.grab().isNull())
        self.assertFalse(w.catalog.wordWrap())

class ResearchTests(unittest.TestCase):
    def rows(self):
        return [{"date":f"2024-01-{i:02}","code":c,"open":10+i*k,"close":11+i*k,"adjustment_factor":1} for i in range(1,12) for c,k in (("A",1),("B",2))]
    def recipe(self): return {"count":1,"lookback":2,"cash":100000,"fee":.1,"frequency":"daily"}
    def test_no_same_day_signal_and_cash(self):
        report=research_bars(self.rows(),self.recipe())
        self.assertFalse(report["pit_guarantee"])
        self.assertTrue(all(t["signal_date"]<t["date"] for t in report["trades"]))
        self.assertTrue(all(n["cash"]>=-1e-6 for n in report["nav"]))
        rows=self.rows(); changed=[dict(r) for r in rows]
        for r in changed:
            if r["date"]=="2024-01-04": r["close"]*=10
        other=research_bars(changed,self.recipe())
        self.assertEqual([t for t in report["trades"] if t["date"]=="2024-01-04"],[t for t in other["trades"] if t["date"]=="2024-01-04"])
        opened=[dict(r) for r in rows]
        for r in opened:
            if r["date"]=="2024-01-04": r["open"]*=.99
        shifted=research_bars(opened,self.recipe())
        self.assertEqual([t["quantity"] for t in report["trades"] if t["date"]=="2024-01-04"],[t["quantity"] for t in shifted["trades"] if t["date"]=="2024-01-04"])
    def test_missing_or_split_refused(self):
        with self.assertRaises(ValueError): research_bars(self.rows()[:-1],self.recipe())
        rows=self.rows(); rows[0]["adjustment_factor"]=.5
        with self.assertRaises(ValueError): research_bars(rows,self.recipe())

if __name__=="__main__": unittest.main()
