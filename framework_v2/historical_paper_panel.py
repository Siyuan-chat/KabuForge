"""GUI for isolated, RESEARCH-ONLY historical paper replay accounts."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


_TEXT = {
    "zh_CN": {
        "title":"历史研究模拟 · RESEARCH-ONLY", "intro":"使用明确选择的本地冻结行情和策略报告，在新教学目录中逐日回放。历史可见时间未认证，不是前向 paper，不会触碰生产账本。",
        "manifest":"冻结行情清单", "report":"策略回测报告", "choose":"选择…", "new_parent":"新教学目录的父目录", "workspace":"教学账本目录",
        "create":"创建隔离账户", "open":"打开并核验", "step":"推进一天", "all":"完整回放", "refresh":"只读刷新", "status":"尚未载入账户。查询不会推进日期。",
        "created":"隔离教学账户已创建。", "opened":"账本已核验并打开；查询未推进。", "stepped":"已回放下一交易日。", "complete":"完整历史回放已完成。", "failed":"操作失败：", "busy":"后台核验或回放中…",
        "clock":"历史回放时钟，不表示行情当时已可见。", "readiness":"RESEARCH-ONLY · PIT 未认证 · 禁止提交订单",
        "summary":"状态 / 游标 / 日期 / 现金 / 权益 / 成交 / 跳过 / 费用", "table_date":"日期", "cash":"现金 JPY", "equity":"权益 JPY", "fills":"成交", "skips":"跳过", "fees":"费用 JPY", "positions":"持仓", "table_tip":"每行对应实际回放日期；横向滚动可查看持仓明细，纵向滚动至末行查看最后日期。",
        "need_inputs":"请选择已冻结的行情清单和 price_research 回测报告。", "need_workspace":"请指定一个尚不存在的独立教学目录。",
        "binding_changed":"所选输入已变化；当前账本仍绑定其原始输入，以下方回执身份为准。",
    },
    "ja_JP": {
        "title":"過去データ研究リプレイ · RESEARCH-ONLY", "intro":"明示的に選択した凍結ローカルデータと戦略レポートを、新しい教材用ディレクトリで日次再生します。過去の可視時刻は未認証で、フォワード paper ではなく、本番台帳に触れません。",
        "manifest":"凍結データマニフェスト", "report":"戦略バックテストレポート", "choose":"選択…", "new_parent":"新しい教材ディレクトリの親", "workspace":"教材台帳ディレクトリ",
        "create":"隔離口座を作成", "open":"開いて検証", "step":"1日進める", "all":"全期間を再生", "refresh":"読み取り専用で更新", "status":"口座未読込。照会では日付を進めません。",
        "created":"隔離教材口座を作成しました。", "opened":"台帳を検証して開きました。照会では進みません。", "stepped":"次の取引日を再生しました。", "complete":"過去データの全期間再生が完了しました。", "failed":"処理に失敗しました：", "busy":"バックグラウンドで検証・再生中…",
        "clock":"過去の再生時刻であり、当時のデータ可視性を示しません。", "readiness":"RESEARCH-ONLY · PIT 未認証 · 注文送信禁止",
        "summary":"状態 / カーソル / 日付 / 現金 / 純資産 / 約定 / スキップ / 手数料", "table_date":"日付", "cash":"現金 JPY", "equity":"純資産 JPY", "fills":"約定", "skips":"スキップ", "fees":"手数料 JPY", "positions":"保有", "table_tip":"各行は実際の再生日です。横スクロールで保有明細を、縦スクロール最下部で最終日を確認できます。",
        "need_inputs":"凍結データマニフェストと price_research レポートを選択してください。", "need_workspace":"まだ存在しない隔離教材ディレクトリを指定してください。",
        "binding_changed":"選択入力が変わりました。現在の台帳は元の入力に紐付いています。下記の台帳IDを確認してください。",
    },
    "en_US": {
        "title":"Historical research replay · RESEARCH-ONLY", "intro":"Replay explicitly selected frozen local bars and a strategy report in a new teaching directory. Historical visibility is unverified; this is not forward paper and never touches a production ledger.",
        "manifest":"Frozen data manifest", "report":"Strategy backtest report", "choose":"Choose…", "new_parent":"Parent for new teaching directory", "workspace":"Teaching ledger directory",
        "create":"Create isolated account", "open":"Open and verify", "step":"Advance one day", "all":"Replay all dates", "refresh":"Read-only refresh", "status":"No account loaded. Queries never advance the replay cursor.",
        "created":"Isolated teaching account created.", "opened":"Ledger verified and opened; query did not advance it.", "stepped":"Replayed the next session.", "complete":"Full historical replay completed.", "failed":"Operation failed: ", "busy":"Verifying or replaying in the background…",
        "clock":"Historical replay clock; it does not prove that data was visible then.", "readiness":"RESEARCH-ONLY · PIT unverified · order submission prohibited",
        "summary":"Status / cursor / dates / cash / equity / fills / skips / fees", "table_date":"Date", "cash":"Cash JPY", "equity":"Equity JPY", "fills":"Fills", "skips":"Skipped", "fees":"Fees JPY", "positions":"Positions", "table_tip":"Each row is an actual replay date. Scroll horizontally for positions and to the bottom for the final date.",
        "need_inputs":"Choose a frozen manifest and a price_research backtest report.", "need_workspace":"Choose a new isolated teaching directory that does not exist yet.",
        "binding_changed":"The selected inputs changed; this ledger remains bound to its original inputs. See the account identity below.",
    },
}


class _PaperWorker(QObject):
    # Python thread identifiers are pointer-sized and can exceed Qt's signed
    # 32-bit int signal payload on Linux. Keep the identifier as a Python object.
    began = Signal(int, object)
    done = Signal(object, str, str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, action: str, manifest: str, report: str, report_sha: str,
                 workspace: str, expected_cursor: int | None = None):
        super().__init__()
        self.action=action; self.manifest=manifest; self.report=report
        self.report_sha=report_sha; self.workspace=workspace; self.expected_cursor=expected_cursor

    @Slot()
    def run(self):
        self.began.emit(os.getpid(),self._thread_ident())
        try:
            from .historical_paper_research import create_historical_paper_research, open_historical_paper_research
            if self.action == "create":
                account=create_historical_paper_research(self.manifest,self.report,self.report_sha,self.workspace)
                message="created"
            else:
                account=open_historical_paper_research(self.workspace)
                message="opened"
                if self.action == "step":
                    event=account.step_next(expected_cursor=self.expected_cursor)
                    if event is None: message="complete"
                    else: message="stepped"
                elif self.action == "all":
                    account.run_all(); message="complete"
                elif self.action != "refresh":
                    raise ValueError("unknown paper panel operation")
            self.done.emit({"summary":account.summary(),"events":account.events(),
                "contract":account.contract,"workspace":str(account.root)},message,self.action)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()

    @staticmethod
    def _thread_ident():
        return threading.get_ident()


class HistoricalPaperPanel(QGroupBox):
    """Bounded asynchronous controls for a separate historical teaching ledger."""
    def __init__(self, workspace: str | Path, language="zh_CN", parent=None):
        super().__init__(parent)
        self.root=Path(workspace).resolve(); self.language=language if language in _TEXT else "zh_CN"
        self.manifest_path=""; self.report_path=""; self.report_sha=""; self.account_path=""
        self._busy=False; self._thread=None; self._worker=None; self.last_result=None
        self._status_key="status"; self._failure_detail=""; self._input_changed=False
        self._operation_dir:Path|None=None; self._operation_action=""; self._operation_error=False
        self._pending_inputs=None
        self.setProperty("ownTranslation",True)
        layout=QVBoxLayout(self)
        self.intro=QLabel(); self.intro.setWordWrap(True); layout.addWidget(self.intro)
        form=QFormLayout(); layout.addLayout(form)
        self.manifest_edit=QLineEdit(); self.manifest_edit.setReadOnly(True); self.manifest_button=QPushButton(); self.manifest_button.clicked.connect(self._choose_manifest)
        form.addRow(QLabel(),self._file_row(self.manifest_edit,self.manifest_button))
        self.report_edit=QLineEdit(); self.report_edit.setReadOnly(True); self.report_button=QPushButton(); self.report_button.clicked.connect(self._choose_report)
        form.addRow(QLabel(),self._file_row(self.report_edit,self.report_button))
        self.workspace_edit=QLineEdit(); self.workspace_edit.setPlaceholderText("...")
        self.workspace_button=QPushButton(); self.workspace_button.clicked.connect(self._choose_workspace)
        form.addRow(QLabel(),self._file_row(self.workspace_edit,self.workspace_button))
        row=QHBoxLayout(); layout.addLayout(row)
        self.create_button=QPushButton(); self.create_button.clicked.connect(self.create_account); row.addWidget(self.create_button)
        self.open_button=QPushButton(); self.open_button.clicked.connect(self.open_account); row.addWidget(self.open_button)
        self.step_button=QPushButton(); self.step_button.clicked.connect(self.step_next); row.addWidget(self.step_button)
        self.all_button=QPushButton(); self.all_button.clicked.connect(self.run_all); row.addWidget(self.all_button)
        self.refresh_button=QPushButton(); self.refresh_button.clicked.connect(self.refresh); row.addWidget(self.refresh_button)
        self.status=QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.summary=QLabel(); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.identity=QLabel(); self.identity.setWordWrap(True); layout.addWidget(self.identity)
        self.operation_log=QLabel(); self.operation_log.setWordWrap(True); layout.addWidget(self.operation_log)
        self.table=QTableWidget(0,7); layout.addWidget(self.table,1)
        self.table.setWordWrap(False); self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.horizontalHeader().setStretchLastSection(False)
        for column,width in enumerate((165,145,150,74,74,145,390)):
            self.table.setColumnWidth(column,width)
        self.table.setToolTip(_TEXT[self.language]["table_tip"])
        self.set_language(self.language); self._update_actions()

    @staticmethod
    def _file_row(edit,button):
        box=QWidget(); row=QHBoxLayout(box); row.setContentsMargins(0,0,0,0); row.addWidget(edit,1); row.addWidget(button); return box

    @property
    def busy(self): return self._busy

    def set_inputs(self,manifest,report,report_sha):
        if self._busy:
            self._pending_inputs=(manifest,report,report_sha)
            self.status.setText(_TEXT[self.language]["busy"]); return False
        previous=(self.manifest_path,self.report_path,self.report_sha)
        self.manifest_path=str(Path(manifest).resolve()) if manifest else ""
        self.report_path=str(Path(report).resolve()) if report else ""
        self.report_sha=str(report_sha or "")
        self.manifest_edit.setText(self.manifest_path); self.report_edit.setText(self.report_path)
        self._input_changed=bool(self.last_result and previous!=(self.manifest_path,self.report_path,self.report_sha))
        if self._input_changed:
            self.status.setText(_TEXT[self.language]["binding_changed"])
            if self.last_result: self._display(self.last_result)
        self._update_actions()
        return True

    def set_language(self,language):
        self.language=language if language in _TEXT else "zh_CN"; t=_TEXT[self.language]
        self.setTitle(t["title"]); self.intro.setText(t["intro"])
        self.manifest_button.setText(t["choose"]); self.report_button.setText(t["choose"]); self.workspace_button.setText(t["choose"])
        rowlabels=self.layout().itemAt(1).layout()
        for i,key in enumerate(("manifest","report","workspace")):
            widget=rowlabels.itemAt(i,QFormLayout.ItemRole.LabelRole).widget(); widget.setText(t[key])
        self.create_button.setText(t["create"]); self.open_button.setText(t["open"]); self.step_button.setText(t["step"])
        self.all_button.setText(t["all"]); self.refresh_button.setText(t["refresh"])
        self.table.setHorizontalHeaderLabels([t[k] for k in ("table_date","cash","equity","fills","skips","fees","positions")])
        self.table.setToolTip(t["table_tip"])
        if self.last_result:
            self.status.setText(t.get(self._status_key,t["status"])+" · "+t["readiness"]); self._display(self.last_result)
        elif self._failure_detail: self.status.setText(t["failed"]+self._failure_detail)
        elif not self._busy: self.status.setText(t["status"])
        self._update_actions()

    def _choose_manifest(self):
        path,_=QFileDialog.getOpenFileName(self,_TEXT[self.language]["manifest"],str(self.root),"JSON (*.json)")
        if path: self.set_inputs(path,self.report_path or None,self.report_sha)

    def _choose_report(self):
        path,_=QFileDialog.getOpenFileName(self,_TEXT[self.language]["report"],str(self.root),"JSON (*.json)")
        if path:
            import hashlib
            digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
            self.set_inputs(self.manifest_path or None,path,digest)

    def _choose_workspace(self):
        parent=QFileDialog.getExistingDirectory(self,_TEXT[self.language]["new_parent"],str(self.root))
        if parent:
            destination=Path(parent)/("historical-paper-"+uuid.uuid4().hex[:12])
            self.account_path=str(destination); self.workspace_edit.setText(str(destination)); self._update_actions()

    def _start(self,action,workspace=None,expected_cursor=None):
        if self._busy: return False
        t=_TEXT[self.language]
        if action=="create" and (not self.manifest_path or not self.report_path or not self.report_sha):
            self.status.setText(t["need_inputs"]); return False
        target=str(workspace or self.workspace_edit.text().strip())
        if not target: self.status.setText(t["need_workspace"]); return False
        if action=="create" and Path(target).exists(): self.status.setText(t["need_workspace"]); return False
        self.account_path=target; self._busy=True; self.status.setText(t["busy"]); self._update_actions()
        self._operation_action=action; self._operation_error=False
        op_root=self.root/"paper-gui-operations"; op_root.mkdir(parents=True,exist_ok=True)
        self._operation_dir=op_root/uuid.uuid4().hex; self._operation_dir.mkdir()
        request={"schema":"kabuforge.paper_gui_operation.v1","action":action,
            "created_at_utc":datetime.now(timezone.utc).isoformat(),"workspace":target,
            "manifest_path":self.manifest_path or None,"manifest_sha256":self._file_sha(self.manifest_path),
            "report_path":self.report_path or None,"report_sha256":self.report_sha or None,
            "expected_cursor":expected_cursor,"readiness":"RESEARCH-ONLY","pit_guarantee":False,
            "recovery":"open the same isolated account to verify/resume; never edit journal directly"}
        self._write_operation("request.json",request)
        self.operation_log.setText(str(self._operation_dir))
        thread=QThread(self); worker=_PaperWorker(action,self.manifest_path,self.report_path,self.report_sha,target,expected_cursor)
        worker.moveToThread(thread); thread.started.connect(worker.run)
        worker.began.connect(lambda pid,ident,op=self._operation_dir,action=action,target=target:self._write_operation("launch.json",{
            "started_at_utc":datetime.now(timezone.utc).isoformat(),"pid":pid,"thread_ident":ident,
            "worker":"framework_v2.historical_paper_panel._PaperWorker.run","action":action,"workspace":target,
            "operation_dir":str(op),"shutdown_policy":"wait for operation thread; never terminate"}))
        worker.done.connect(self._completed); worker.failed.connect(self._failed); worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater); thread.finished.connect(lambda th=thread:self._thread_finished(th))
        self._thread=thread; self._worker=worker; thread.start(); return True

    @Slot(object,str,str)
    def _completed(self,result,message,action):
        self.last_result=result; self.account_path=result["workspace"]; self.workspace_edit.setText(self.account_path)
        self._status_key=message; self._failure_detail=""; self.status.setText(_TEXT[self.language][message]+" · "+_TEXT[self.language]["readiness"]); self._display(result)
        self._operation_error=False
        self._write_operation("result.json",{"schema":"kabuforge.paper_gui_operation_result.v1","status":result["summary"]["status"],
            "action":action,"summary":result["summary"],"contract_sha256":result["contract"].get("contract_sha256"),
            "journal_sha256":result["summary"].get("journal_sha256"),"event_count":len(result["events"]),
            "workspace":result["workspace"],"readiness":"RESEARCH-ONLY","pit_guarantee":False})

    @Slot(str)
    def _failed(self,reason):
        self._failure_detail=reason; self.last_result=None; self._input_changed=False
        self.summary.clear(); self.identity.clear(); self.table.setRowCount(0)
        self._operation_error=True
        self._write_operation("failure.json",{"schema":"kabuforge.paper_gui_operation_failure.v1","status":"FAILED",
            "action":self._operation_action,"error_type":reason.split(":",1)[0],"reason":reason[:2000],
            "recorded_at_utc":datetime.now(timezone.utc).isoformat(),"readiness":"RESEARCH-ONLY","pit_guarantee":False})
        self.status.setText(_TEXT[self.language]["failed"]+reason)

    def _thread_finished(self,thread):
        if self._thread is thread:
            self._write_operation("exit.json",{"action":self._operation_action,"status":"FAILED" if self._operation_error else "COMPLETED",
                "exit_code":1 if self._operation_error else 0,"finished_at_utc":datetime.now(timezone.utc).isoformat(),
                "operation_dir":str(self._operation_dir) if self._operation_dir else None})
            self._thread=None; self._worker=None; self._busy=False; self._update_actions()
            pending=self._pending_inputs; self._pending_inputs=None
            if pending is not None: self.set_inputs(*pending)
        thread.deleteLater()

    @staticmethod
    def _file_sha(path):
        try: return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None
        except OSError: return None

    def _write_operation(self,name,value):
        if self._operation_dir is None: return
        try: (self._operation_dir/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
        except OSError: pass

    def _display(self,result):
        summary=result["summary"]; t=_TEXT[self.language]
        source=(result.get("contract") or {}).get("source_identity",{})
        input_marker=(" · "+t["binding_changed"]) if self._input_changed else ""
        self.identity.setText(f"{t['manifest']}: {source.get('manifest_sha256','—')} · {t['report']}: {source.get('report_sha256','—')} · {result.get('workspace','—')}{input_marker}")
        status={"COMPLETED":self._localized("Completed","完了","已完成"),"IN_PROGRESS":self._localized("In progress","進行中","进行中")}.get(summary["status"],summary["status"])
        self.summary.setText(f"{status} · {summary['cursor']}/{summary['total_dates']} · {summary['last_date'] or '—'} · {t['cash']} {summary['cash']:,.2f} · {t['equity']} {summary['equity']:,.2f} · {t['fills']} {summary['fills']} · {t['skips']} {summary['skips']} · {t['fees']} {summary['fees']:,.2f} · RESEARCH-ONLY")
        events=result["events"]; self.table.setRowCount(len(events))
        for r,event in enumerate(events):
            vals=(event.get("at",""),f"{event.get('cash',0):,.2f}",f"{event.get('equity',0):,.2f}",str(len(event.get("fills",[]))),str(len(event.get("skips",[]))),f"{event.get('fees',0):,.2f}",json.dumps(event.get("positions",[]),ensure_ascii=False))
            for c,value in enumerate(vals):
                item=QTableWidgetItem(value); item.setToolTip(value); self.table.setItem(r,c,item)
        self.table.scrollToBottom()

    def _localized(self,en,ja,zh): return {"en_US":en,"ja_JP":ja,"zh_CN":zh}[self.language]

    def create_account(self): return self._start("create")
    def open_account(self): return self._start("refresh")
    def refresh(self): return self._start("refresh")
    def step_next(self):
        if not self.last_result: return self.open_account()
        return self._start("step",self.account_path,int(self.last_result["summary"]["cursor"]))
    def run_all(self): return self._start("all",self.account_path)

    def _update_actions(self):
        enabled=not self._busy
        for widget in (self.manifest_button,self.report_button,self.workspace_button): widget.setEnabled(enabled)
        self.create_button.setEnabled(enabled and bool(self.manifest_path and self.report_path and self.report_sha and self.workspace_edit.text().strip()))
        exists=bool(self.workspace_edit.text().strip() and Path(self.workspace_edit.text().strip()).is_dir())
        for button in (self.open_button,self.refresh_button): button.setEnabled(enabled and exists)
        ready=enabled and exists and self.last_result is not None and self.last_result["summary"]["cursor"]<self.last_result["summary"]["total_dates"]
        self.step_button.setEnabled(ready); self.all_button.setEnabled(ready)

    def closeEvent(self,event):
        if self._busy: event.ignore(); return
        super().closeEvent(event)
