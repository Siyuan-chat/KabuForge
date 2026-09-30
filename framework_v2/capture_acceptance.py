"""Exercise real Qt widgets with synthetic/mock inputs and retain evidence.

No real credentials, network, production caches or paper accounts are used.
Run with --output pointing to a NEW directory; set QT_SCALE_FACTOR per run.
"""
import argparse,os,sys,json,time,hashlib
from datetime import datetime,timezone,timedelta,date
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from .product_ui import ProductWorkbench
from .data_connection import download_bars

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--output",required=True,type=Path); args=parser.parse_args()
    root=args.output.resolve(); root.mkdir(parents=True,exist_ok=False)
    app=QApplication.instance() or QApplication([])
    with patch("framework_v2.data_connection.load_api_key",return_value=None): window=ProductWorkbench(root/"workspace")
    window.show(); operations=[]
    def record(action,**details):
        operations.append({"at":datetime.now(timezone.utc).isoformat(),"action":action,**details})
        (root/"operations.json").write_text(json.dumps(operations,ensure_ascii=False,indent=2),encoding="utf-8")
    def wait():
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            app.processEvents(); time.sleep(.01)
            if not window.jobs.busy:
                app.processEvents()
                if not window.jobs.busy: break
        if window.jobs.busy: window.jobs.cancel(); raise RuntimeError("timeout")
        job=window.jobs.jobs[-1]
        record("job_finished",job_id=job["job_id"],status=job["status"],manifest=job["manifest"])
        if job["status"]!="COMPLETED": raise RuntimeError(str(job))
    def capture(name,page=None,width=1320,height=900):
        if page is not None: window.nav.setCurrentRow(page)
        window.resize(width,height)
        for _ in range(5): app.processEvents()
        path=root/(name+".png")
        if not window.grab().save(str(path)): raise RuntimeError("capture failed")
        record("screenshot",path=str(path),language=window.language,size=[window.width(),window.height()],scale=os.environ.get("QT_SCALE_FACTOR","1"),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    try:
        record("scope",data="synthetic demo + mocked J-Quants v2 responses",real_network=False,real_credentials=False,platform=app.platformName(),pid=os.getpid(),command=sys.argv)
        from .brand_theme import BRAND_DIR,DARK
        assert not window.windowIcon().isNull() and window.brand_logo.renderer().isValid()
        window.windowIcon().pixmap(128,128).save(str(root/"application_icon.png"))
        record("brand",name="KabuForge",palette=DARK,assets={name:hashlib.sha256((BRAND_DIR/name).read_bytes()).hexdigest() for name in ("app-icon.svg","logo-horizontal-dark.svg","logo-horizontal-light.png","tokens.css")})
        for language in ("zh_CN","ja_JP","en_US"):
            window.language_picker.setCurrentIndex(window.language_picker.findData(language)); capture(language+"_home",0)
        window.language_picker.setCurrentIndex(0)
        window.demo_button.click(); wait(); record("offline_demo_created",run=str(window.run_path))
        window.sentence.setText("每周选3只股票，等权"); window.parse_button.click()
        assert window.holding_count.value()==3
        window.create_button.click(); wait()
        window.guided_run.click(); wait(); assert window.report and window.report["nav"]
        record("guided_backtest_completed",nav_rows=len(window.report["nav"]))
        for language in ("zh_CN","ja_JP","en_US"):
            window.language_picker.setCurrentIndex(window.language_picker.findData(language))
            capture(language+"_strategy",1); capture(language+"_data",2); capture(language+"_results",3)
            window.show_help(); help_dialog=window.help_dialog
            help_dialog.browser.scrollToAnchor("contents"); app.processEvents()
            help_dialog.grab().save(str(root/(language+"_manual_contents.png")))
            query={"zh_CN":"密钥","ja_JP":"キー","en_US":"key"}[language]
            help_dialog.search.setText(query); help_dialog._select(help_dialog.contents.item(0)); app.processEvents()
            assert help_dialog.contents.count()>0
            help_dialog.grab().save(str(root/(language+"_manual_search.png")))
            record("manual_search",language=language,query=query,results=help_dialog.contents.count(),chapter=help_dialog.chapter)
            help_dialog.hide()
        window.language_picker.setCurrentIndex(0); capture("zh_CN_narrow",1,900,720)
        window.mode.setCurrentIndex(window.mode.findData("paper")); assert window.start_action("preflight"); wait()
        assert window.start_action("simulate"); wait(); assert window.query_journal(); wait()
        capture("zh_CN_paper",4); record("isolated_paper_query",blocked=window.paper_blocked)
        class Response:
            status_code=200
            def __init__(self,rows): self.rows=rows
            def json(self): return {"data":self.rows}
        class Session:
            def get(self,url,headers,params,timeout,**kwargs):
                code=params["code"]; k=1 if code=="7203" else 2
                return Response([{"Date":(date(2024,1,1)+timedelta(days=i)).isoformat(),"Code":code,"O":100+i*k,"C":101+i*k,"AdjFactor":1} for i in range(75) if (date(2024,1,1)+timedelta(days=i)).weekday()<5])
        manifest=download_bars(root/"workspace","fixture-not-a-real-key",["7203","6758"],"2024-01-01","2024-03-15",session=Session())
        window._market_ready(str(manifest)); window.template.setCurrentIndex(1); window.holding_count.setValue(2); window.lookback.setValue(5)
        window.create_button.click(); assert window.guide_recipe
        window.guided_run.click(); wait(); assert window.report["model"]=="daily_bar_next_open_research_v1"
        capture("zh_CN_price_research_fixture",3); record("download_to_research",fixture=True,manifest=str(manifest),nav_rows=len(window.report["nav"]))
        hashes={str(p.relative_to(Path(__file__).parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")}
        (root/"source_hashes.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")
        record("acceptance_complete",result="PASS",limitations=["No real J-Quants entitlement/network verification", "Qt widget captures, not native mouse automation", "No strategy readiness certification"])
    finally:
        window.document._dirty=False; window.close(); app.processEvents()
    print(json.dumps({"output":str(root),"operations":len(operations),"screenshots":len(list(root.glob('*.png')))},ensure_ascii=False))

if __name__=="__main__": main()
