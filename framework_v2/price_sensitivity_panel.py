"""User-facing, offline and asynchronous price-sensitivity comparison panel."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import uuid

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QWidget, QHeaderView)


_TEXT = {
    "zh_CN": {"title":"费用与延迟敏感性（预注册）", "source":"来源运行", "run":"运行三个固定情景",
        "idle":"请先在回测结果页打开一个价格研究 report.json。", "running":"正在离线运行全部三个情景…",
        "ready":"三个情景均已完成；均显示，不择优。", "failed":"敏感性运行失败：", "stale":"结果输入已改变；旧结果已清除。",
        "wait_close":"敏感性任务仍在运行，请等待其完成后再关闭窗口。", "case":["0.1% 基线策略重跑","0.2% 费用策略重跑","+1 个观测日固定数量执行诊断"],
        "columns":["情景 / 方法","日期范围 / 日数","成交 / 跳过","费用（JPY）","期末净值","期末现金（JPY）","期末权益（JPY）","最大回撤"],
        "method":["同策略重跑；冻结行情与配方，费用储备后重新定量。","同策略重跑；数量随费用约束重新计算。","冻结基线订单数量，延后至下一实际观测日开盘；不重新选股。"],
        "identity":"运行身份", "empty":"运行后显示三个情景的净值曲线。", "status":"状态", "source_missing":"当前打开的报告不是带冻结研究输入的价格研究运行。",
        "logs":"运行目录 / 日志", "filename":"情景", "pit":"研究用途；PIT 保证：否", "chart_case":["基线 0.1%","重跑 0.2%","+1日固定量"]},
    "ja_JP": {"title":"手数料・遅延感度（事前登録）", "source":"入力実行", "run":"固定3シナリオを実行",
        "idle":"バックテスト結果で価格研究の report.json を開いてください。", "running":"3シナリオをオフラインで実行中…",
        "ready":"3シナリオが完了しました。すべて表示し、最良案は選びません。", "failed":"感度分析に失敗：", "stale":"入力が変更されたため、古い結果を消去しました。",
        "wait_close":"感度分析の完了後にウィンドウを閉じてください。", "case":["0.1% 基準戦略の再実行","0.2% 手数料戦略の再実行","+1観測日・数量固定の執行診断"],
        "columns":["シナリオ / 方法","期間 / 日数","約定 / 未約定","手数料（JPY）","期末NAV","期末現金（JPY）","期末評価額（JPY）","最大DD"],
        "method":["同一戦略を再実行。データとレシピを固定し、手数料控除後に数量を再計算。","同一戦略を再実行。手数料制約に応じ数量を再計算。","基準注文数量を固定し、次の実観測日の寄付で再生。銘柄選択なし。"],
        "identity":"実行識別子", "empty":"実行後に3シナリオのNAVを表示します。", "status":"状態", "source_missing":"現在開いているレポートには凍結済み価格研究入力がありません。",
        "logs":"実行フォルダー / ログ", "filename":"シナリオ", "pit":"研究専用；PIT保証なし", "chart_case":["基準0.1%","再実行0.2%","+1日数量固定"]},
    "en_US": {"title":"Fee and delay sensitivity (preregistered)", "source":"Source run", "run":"Run all three fixed scenarios",
        "idle":"Open a price-research report.json from the backtest results page first.", "running":"Running all three scenarios offline…",
        "ready":"All three scenarios completed; all are shown, none selected.", "failed":"Sensitivity run failed: ", "stale":"The input changed; the previous result was cleared.",
        "wait_close":"Wait for the sensitivity job to finish before closing the window.", "case":["0.1% baseline strategy rerun","0.2% fee strategy rerun","+1 observed session, fixed-quantity execution diagnostic"],
        "columns":["Scenario / method","Date range / days","Fills / skips","Fees (JPY)","Ending NAV","Ending cash (JPY)","Ending equity (JPY)","Max drawdown"],
        "method":["Same strategy rerun on frozen bars/recipe; sizing is recalculated after fee reserve.","Same strategy rerun; quantities reflect the higher fee constraint.","Replay baseline fixed quantities at the next observed open; no reselection."],
        "identity":"Run identity", "empty":"The three NAV paths appear after the run.", "status":"Status", "source_missing":"The currently opened report has no frozen price-research inputs.",
        "logs":"Job directory / logs", "filename":"Scenario", "pit":"Research only; PIT guarantee: no", "chart_case":["Base 0.1%","Rerun 0.2%","+1 day replay"]},
}

_SCENARIO_IDS = ("baseline_fee_0_1pct", "higher_fee_0_2pct", "one_observed_session_delay")
_COLORS = ("#4cc9f0", "#f6bd60", "#c77dff")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class _NavChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.paths=[]; self.labels=[]; self.setMinimumHeight(210)
        self.axis_labels={}; self.axis_dates=(None,None)
        self.setStyleSheet("background:#111827; color:#e5e7eb;")

    def set_scenarios(self, scenarios, labels):
        self.paths=[scenario.get("financial_path",{}).get("nav") or [] for scenario in scenarios]
        self.labels=list(labels); self.update()

    def clear(self): self.paths=[]; self.labels=[]; self.update()

    def paintEvent(self, event):
        self.language=getattr(self,"language","zh_CN")
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(),QColor("#111827")); rect=self.rect().adjusted(58,36,-20,-34)
        self.axis_labels={}
        painter.setPen(QPen(QColor("#344256"),1))
        for index in range(5):
            y=rect.top()+rect.height()*index/4; painter.drawLine(rect.left(),int(y),rect.right(),int(y))
        values=[float(row["nav"]) for path in self.paths for row in path if isinstance(row,dict) and _finite(row.get("nav"))]
        if not values:
            painter.setPen(QColor("#cbd5e1")); painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,_TEXT.get(getattr(self,"language","zh_CN"),_TEXT["zh_CN"])["empty"]); painter.end(); return
        low=min(values); high=max(values); span=max(high-low,1e-12)
        painter.setFont(QFont("Microsoft YaHei UI",8)); painter.setPen(QColor("#cbd5e1"))
        def draw_axis_label(key,x,y,width,height,alignment,text):
            bounds=(int(x),int(y),int(width),int(height))
            self.axis_labels[key]={"text":str(text),"rect":bounds}
            painter.drawText(*bounds,int(alignment),str(text))
        for index in range(5):
            value=high-span*index/4; y=int(rect.top()+rect.height()*index/4)
            painter.drawText(2,y-8,52,16,int(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter),f"{value:.3f}")
        for i,path in enumerate(self.paths):
            points=[]
            for row in path:
                if not isinstance(row,dict) or not _finite(row.get("nav")): continue
                x=rect.left()+rect.width()*len(points)/max(1,len(path)-1)
                y=rect.bottom()-(float(row["nav"])-low)/span*rect.height()
                points.append((int(x),int(y)))
            painter.setPen(QPen(QColor(_COLORS[i%len(_COLORS)]),2))
            for left,right in zip(points,points[1:]): painter.drawLine(left[0],left[1],right[0],right[1])
        first_date=last_date=None
        for row in self.paths[0] if self.paths else []:
            if not isinstance(row,dict) or not _finite(row.get("nav")): continue
            value=row.get("at")
            if first_date is None: first_date=value
            last_date=value
        self.axis_dates=(first_date,last_date)
        painter.setPen(QColor("#94a3b8"))
        draw_axis_label("nav",4,2,48,16,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,"NAV")
        date_y=self.height()-27; date_height=18; date_width=rect.width()//2
        draw_axis_label("start_date",rect.left(),date_y,date_width,date_height,
            Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,first_date or "—")
        draw_axis_label("end_date",rect.left()+rect.width()-date_width,date_y,date_width,date_height,
            Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,last_date or "—")
        x=rect.left()
        for i,name in enumerate(self.labels):
            painter.setPen(QPen(QColor(_COLORS[i%len(_COLORS)]),3)); painter.drawLine(x,13,x+18,13)
            painter.setPen(QColor("#e5e7eb")); painter.drawText(x+23,18,150,16,
                int(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter),name); x+=max(130,int(rect.width()/3))
        painter.end()


def _finite(value):
    try:
        number=float(value)
        return number==number and abs(number)!=float("inf")
    except (TypeError,ValueError,OverflowError): return False


class PriceSensitivityPanel(QGroupBox):
    """Runs the static local sensitivity worker only after an explicit click."""
    def __init__(self, workspace, language="zh_CN", parent=None):
        super().__init__(parent); self.workspace=Path(workspace).resolve(); self.language=language if language in _TEXT else "zh_CN"
        self.source_report=None; self.source_run=None; self.source_sha256=None; self.generation=0
        self.process=None; self.job_dir=None; self._active_generation=None; self.result=None; self._failure_detail=None; self._closed=False
        root=QVBoxLayout(self); self.identity=QLabel(); self.identity.setWordWrap(True); root.addWidget(self.identity)
        self.methods=QLabel(); self.methods.setWordWrap(True); root.addWidget(self.methods)
        self.run_button=QPushButton(); self.run_button.clicked.connect(self.run); root.addWidget(self.run_button)
        self.status=QLabel(); self.status.setWordWrap(True); root.addWidget(self.status)
        self.table=QTableWidget(0,8); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table)
        self.chart=_NavChart(); self.chart.setAccessibleName("Scenario NAV comparison"); root.addWidget(self.chart,1)
        self.logs=QLabel(); self.logs.setWordWrap(True); root.addWidget(self.logs)
        self.set_language(self.language); self._render_source()

    @property
    def busy(self): return self.process is not None and self.process.state()!=QProcess.ProcessState.NotRunning

    def set_source(self, report_path):
        candidate=None; run_dir=None; digest=None
        if report_path:
            try:
                path=Path(report_path).expanduser().resolve(strict=True)
                raw=path.read_bytes()
                report=json.loads(raw)
                if (path.name=="report.json" and (path.parent/"research_inputs.json").is_file()
                        and isinstance(report,dict) and report.get("model")=="daily_bar_next_open_research_v1"):
                    candidate=path; run_dir=path.parent; digest=hashlib.sha256(raw).hexdigest()
            except (OSError,ValueError): pass
        if (candidate,run_dir,digest)==(self.source_report,self.source_run,self.source_sha256): return candidate is not None
        self.generation+=1; self.source_report=candidate; self.source_run=run_dir; self.source_sha256=digest
        self.result=None; self._failure_detail=None; self._clear_display()
        if self.busy: self.status.setText(_TEXT[self.language]["stale"])
        else: self.status.setText(_TEXT[self.language]["idle"] if candidate else _TEXT[self.language]["source_missing"])
        self._render_source(); self._update_enabled(); return candidate is not None

    def _render_source(self):
        t=_TEXT[self.language]
        self.identity.setText(f"{t['identity']}: {self.source_run or '—'}\nSHA256: {self.source_sha256 or '—'}")
        self.methods.setText("\n".join(f"• {name}: {method}" for name,method in zip(t["case"],t["method"])))

    def _clear_display(self):
        self.table.setRowCount(0); self.chart.clear(); self.logs.clear()

    def _update_enabled(self): self.run_button.setEnabled(bool(self.source_report and not self.busy))

    def set_language(self, language):
        self.language=language if language in _TEXT else "zh_CN"; t=_TEXT[self.language]
        self.setTitle(t["title"]); self.run_button.setText(t["run"]); self.chart.language=self.language; self.chart.update()
        self.table.setHorizontalHeaderLabels(t["columns"]); self._render_source()
        if self.result: self._show_result(self.result)
        elif self.busy: self.status.setText(t["running"])
        elif self._failure_detail: self.status.setText(t["failed"]+self._failure_detail)
        elif not self.source_report: self.status.setText(t["idle"])

    def _runtime_environment(self):
        from .research_runtime import resolve_research_runtime
        root=Path(__file__).resolve().parents[1]
        plat="win-amd64" if os.name=="nt" and sys.maxsize>2**32 else sysconfig.get_platform()
        report=json.loads(self.source_report.read_text(encoding="utf-8"))
        recipe=(report.get("workbench_configs") or {}).get("recipe") or {}
        provider="talib" if report.get("strategy_template")=="sma_crossover" and recipe.get("signal_provider")=="talib" else "native"
        runtime=resolve_research_runtime(root,platform.python_version(),plat,
            operation="indicators" if provider=="talib" else "native",
            choices={"provider":"talib"} if provider=="talib" else None)
        if not runtime.get("enabled"):
            raise RuntimeError("selected scenario dependencies are unavailable: "+str(runtime.get("reason") or "runtime unavailable"))
        env=QProcessEnvironment()
        for key in ("PATH","SYSTEMROOT","WINDIR","TEMP","TMP","USERPROFILE","APPDATA","LOCALAPPDATA","HOMEDRIVE","HOMEPATH"):
            value=os.environ.get(key)
            if value: env.insert(key,value)
        # The price research worker uses the GUI runtime and optional TA-Lib
        # target only when their local receipts have passed the resolver.
        env.insert("PYTHONPATH",os.pathsep.join([*runtime.get("paths",[]),str(root)]))
        env.insert("PYTHONNOUSERSITE","1"); env.insert("PYTHONDONTWRITEBYTECODE","1")
        env.insert("PYTHONIOENCODING","utf-8")
        return env

    def run(self):
        if self.busy or not self.source_report or not self.source_run or not self.source_sha256: return False
        try:
            if _sha256(self.source_report)!=self.source_sha256: raise ValueError("Selected report changed; reopen it before running.")
            env=self._runtime_environment(); job_id=uuid.uuid4().hex
            job_dir=self.workspace/"price-sensitivity"/"jobs"/job_id; job_dir.mkdir(parents=True,exist_ok=False)
            request={"schema":"kabuforge.price_sensitivity_request.v1","job_id":job_id,
                "operation":"price_sensitivity","run_directory":str(self.source_run),"report_sha256":self.source_sha256}
            request_raw=json.dumps(request,ensure_ascii=False,indent=2,allow_nan=False).encode("utf-8")
            (job_dir/"request.json").write_bytes(request_raw)
            (job_dir/"stdout.log").touch(); (job_dir/"stderr.log").touch()
            process=QProcess(self); process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
            process.setProcessEnvironment(env); process.setProgram(sys.executable)
            process.setArguments(["-B","-u","-m","framework_v2.price_sensitivity_worker","--workspace",str(self.workspace),"--job-id",job_id])
            process.setStandardOutputFile(str(job_dir/"stdout.log")); process.setStandardErrorFile(str(job_dir/"stderr.log"))
            generation=self.generation; self._active_generation=generation; self.job_dir=job_dir; self.result=None; self._clear_display()
            self.process=process; self.result=None; self._failure_detail=None
            self.status.setText(_TEXT[self.language]["running"]); self._update_enabled()
            request_sha=hashlib.sha256(request_raw).hexdigest()
            process.started.connect(lambda p=process,d=job_dir,j=job_id,r=request_sha,q=request:self._record_launch(p,d,j,r,q))
            process.finished.connect(lambda code,state,p=process,d=job_dir,g=generation:self._finished(p,d,g,code,state))
            process.errorOccurred.connect(lambda error,p=process,d=job_dir,g=generation:self._error(p,d,g,error))
            process.start(); return True
        except Exception as exc:
            self._failure_detail=str(exc); self.status.setText(_TEXT[self.language]["failed"]+self._failure_detail); self._update_enabled(); return False

    def _record_launch(self,process,job_dir,job_id,request_sha,request):
        payload={"schema":"kabuforge.price_sensitivity_launch.v1","job_id":job_id,
            "started_at_utc":datetime.now(timezone.utc).isoformat(),"pid":int(process.processId()),
            "program":sys.executable,"arguments":process.arguments(),"request_sha256":request_sha,
            "source_run_directory":request["run_directory"],"source_report_sha256":request["report_sha256"],
            "logs":{"stdout":str(job_dir/"stdout.log"),"stderr":str(job_dir/"stderr.log")},
            "recovery_point":str(job_dir),"exit_policy":"wait for completion; no forced termination"}
        self._write_receipt(job_dir/"launch.json",payload)

    @staticmethod
    def _write_receipt(path,payload):
        try:
            with path.open("x",encoding="utf-8",newline="\n") as stream: json.dump(payload,stream,ensure_ascii=False,indent=2,allow_nan=False)
        except FileExistsError: pass

    def _finished(self,process,job_dir,generation,code,state):
        if process is not self.process: return
        exit_payload={"schema":"kabuforge.price_sensitivity_exit.v1","job_id":job_dir.name,
            "finished_at_utc":datetime.now(timezone.utc).isoformat(),"exit_code":int(code),"exit_status":str(state)}
        self._write_receipt(job_dir/"exit.json",exit_payload)
        process.deleteLater(); self.process=None; self._update_enabled()
        if generation!=self.generation or self._active_generation!=self.generation:
            self.result=None; self._clear_display(); self.status.setText(_TEXT[self.language]["stale"]); return
        try:
            receipt=json.loads((job_dir/"result.json").read_text(encoding="utf-8"))
            if (code!=0 or receipt.get("schema")!="kabuforge.price_sensitivity_worker_result.v1"
                    or receipt.get("job_id")!=job_dir.name or receipt.get("operation")!="price_sensitivity"
                    or receipt.get("status")!="COMPLETED"):
                raise ValueError("worker did not complete the selected job")
            result_path=Path(receipt["result_path"]).resolve(strict=True)
            if not result_path.is_relative_to((job_dir/"outputs").resolve(strict=True)): raise ValueError("result path escaped job output")
            if _sha256(result_path)!=receipt.get("result_sha256"): raise ValueError("result SHA256 mismatch")
            value=json.loads(result_path.read_text(encoding="utf-8"))
            source_identity=value.get("source_identity",{})
            if (source_identity.get("report_sha256")!=self.source_sha256
                    or Path(source_identity.get("run_directory","")).resolve()!=self.source_run):
                raise ValueError("result source identity does not match current report")
            cases=value.get("scenarios")
            if value.get("status")!="COMPLETED" or not isinstance(cases,list) or tuple(row.get("id") for row in cases)!=_SCENARIO_IDS:
                raise ValueError("worker result does not contain all fixed scenarios")
            self.result=value; self._show_result(value)
        except Exception as exc:
            self.result=None; self._failure_detail=str(exc); self._clear_display(); self.status.setText(_TEXT[self.language]["failed"]+self._failure_detail)
            self.logs.setText(f"{_TEXT[self.language]['logs']}: {job_dir}\nstdout: {job_dir/'stdout.log'}\nstderr: {job_dir/'stderr.log'}\nreceipt: {job_dir/'failure.json' if (job_dir/'failure.json').is_file() else job_dir/'result.json'}")
        self._update_enabled()

    def _error(self,process,job_dir,generation,error):
        if process is not self.process or process.state()!=QProcess.ProcessState.NotRunning: return
        reason=process.errorString(); error_name=getattr(error,"name",str(error))
        self._write_receipt(job_dir/"failure.json",{"schema":"kabuforge.price_sensitivity_failure.v1","job_id":job_dir.name,
            "finished_at_utc":datetime.now(timezone.utc).isoformat(),"pid":None,"error_type":error_name,"reason":reason})
        self._write_receipt(job_dir/"exit.json",{"schema":"kabuforge.price_sensitivity_exit.v1","job_id":job_dir.name,
            "finished_at_utc":datetime.now(timezone.utc).isoformat(),"exit_code":None,"exit_status":"FailedToStart"})
        process.deleteLater(); self.process=None; self._update_enabled()
        self._failure_detail=reason; self.status.setText(_TEXT[self.language]["failed"]+reason)
        self.logs.setText(f"{_TEXT[self.language]['logs']}: {job_dir}\nstderr: {job_dir/'stderr.log'}\nreceipt: {job_dir/'failure.json'}")

    def _show_result(self,value):
        t=_TEXT[self.language]; cases=value["scenarios"]; self.table.setRowCount(3)
        for row,case in enumerate(cases):
            summary=case; fields=(t["case"][row],f"{summary.get('start_date')} – {summary.get('end_date')} / {summary.get('nav_observations')}",
                f"{summary.get('fills')} / {summary.get('skips')}",_fmt(summary.get("fees")),_fmt(summary.get("ending_nav")),
                _fmt(summary.get("ending_cash")),_fmt(summary.get("ending_equity")),_pct(_max_drawdown(case.get("financial_path",{}).get("nav") or [])))
            for col,text in enumerate(fields):
                item=QTableWidgetItem(text); item.setToolTip((summary.get("method","")+"\n"+summary.get("quantity_policy","")+"\n"+summary.get("scenario_order_schedule_sha256", "")))
                self.table.setItem(row,col,item)
        self.chart.set_scenarios(cases,t["chart_case"]); self.status.setText(t["ready"])
        self.logs.setText(f"{t['logs']}: {self.job_dir}\nreport SHA256: {value.get('source_identity',{}).get('report_sha256')}\nresult SHA256: {_sha256(self.job_dir/'outputs'/'scenario-run'/'price_sensitivity.json')}\n{t['pit']}")


def _fmt(value): return "—" if not _finite(value) else f"{float(value):,.4f}"


def _pct(value): return "—" if not _finite(value) else f"{float(value):.2%}"


def _max_drawdown(rows):
    reported=[float(row["drawdown"]) for row in rows if isinstance(row,dict) and _finite(row.get("drawdown"))]
    if reported and len(reported)==len(rows): return min(reported)
    values=[float(row["nav"]) for row in rows if isinstance(row,dict) and _finite(row.get("nav"))]
    peak=None; dd=[]
    for value in values:
        peak=value if peak is None else max(peak,value)
        dd.append(value/peak-1.0)
    return min(dd) if dd else None
