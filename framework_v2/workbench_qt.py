"""Unified PySide6 workbench. Legacy entry points remain untouched."""
from __future__ import annotations
import argparse,json,hashlib,os
from decimal import Decimal
from pathlib import Path
import sys
from PySide6.QtCore import Qt,QSettings,QSignalBlocker,QTimer
from PySide6.QtGui import QKeySequence,QShortcut,QFontDatabase,QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QGridLayout,QFormLayout,QSplitter,QListWidget,QListWidgetItem,QStackedWidget,QScrollArea,
    QLabel,QPushButton,QLineEdit,QComboBox,QPlainTextEdit,QTabWidget,QGroupBox,QFileDialog,QMessageBox)
from .workbench_theme import APP_STYLESHEET
from .workbench_widgets import DataTable,SeriesChart,label
from .workbench_jobs import JobController
from .workbench_model import ConfigDocument
from .workbench_service import WorkbenchService

PAGES=["工作台","策略与因子","数据与股票池","回测研究","纸上交易","券商连接","运行记录"]

class WorkbenchWindow(QMainWindow):
    def __init__(self,workspace,service=None):
        super().__init__()
        # Windows offscreen Qt does not enumerate system fonts. Register local
        # fonts only when the platform supplies none; native desktop keeps its defaults.
        if not QFontDatabase.families():
            for name in ("msyh.ttc","msyhbd.ttc","segoeui.ttf"):
                font_path=Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/name
                if font_path.is_file(): QFontDatabase.addApplicationFont(str(font_path))
            QApplication.instance().setFont(QFont("Microsoft YaHei UI",10))
        self.workspace=Path(workspace).resolve(); self.workspace.mkdir(parents=True,exist_ok=True)
        self.service=service or WorkbenchService(); self.document=ConfigDocument()
        self.run_path=None; self.document_path=None; self.preflight_result=None; self.report=None
        self.json_invalid=False; self.form_errors={}; self.fields={}; self.tables=[]; self.catalog_rows=[]
        self.settings=QSettings(str(self.workspace/"ui.ini"),QSettings.Format.IniFormat)
        self.jobs=JobController(self.workspace,self); self.jobs.started.connect(self._job_started)
        self.jobs.finished.connect(self._job_finished); self.jobs.log.connect(self._job_log)
        self.setWindowTitle("量化工作台 · Private Engine v2"); self.resize(1320,860); self.setMinimumSize(820,600)
        self.setStyleSheet(APP_STYLESHEET+"QPlainTextEdit {background:#11151C;color:#E9ECF2;border:1px solid #303744;} QTableView {alternate-background-color:#151A22;} QListWidget {border:0;} QLineEdit[invalid='true'] {border-color:#FF6B63;}")
        root=QWidget(); outer=QHBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0); self.setCentralWidget(root)
        rail=QWidget(); rail.setObjectName("sideRail"); rail.setFixedWidth(182); side=QVBoxLayout(rail); side.setContentsMargins(14,22,14,12)
        side.addWidget(label("PRIVATE ENGINE", "brandEyebrow")); side.addWidget(label("量化工作台", "brandTitle"))
        self.nav=QListWidget(); self.nav.addItems(PAGES); self.nav.setSpacing(5); side.addWidget(self.nav,1)
        self.help_button=QPushButton("设置与帮助"); self.help_button.clicked.connect(self.show_help); side.addWidget(self.help_button)
        side.addWidget(label("本地研究 / 模拟\n真实交易未启用","subtleText")); outer.addWidget(rail)
        body=QWidget(); layout=QVBoxLayout(body); layout.setContentsMargins(20,14,20,10)
        top=QGridLayout(); self.strategy_badge=label("策略：尚未选择","brandTitle")
        self.mode=QComboBox(); self.mode.addItem("回测 · 本地模拟","backtest"); self.mode.addItem("Paper · 独立模拟账户","paper"); self.mode.addItem("FakeBroker · 协议模拟","fake"); self.mode.addItem("券商 · 仅能力查看","broker")
        self.mode.setAccessibleName("执行模式"); self.mode.currentIndexChanged.connect(self._mode_changed)
        self.account_badge=label("账户：未选择","subtleText"); self.cutoff_badge=label("数据截止：未预检","subtleText")
        top.addWidget(self.strategy_badge,0,0); top.addWidget(self.mode,0,1); top.addWidget(self.account_badge,1,0); top.addWidget(self.cutoff_badge,1,1)
        top.setColumnStretch(0,1); layout.addLayout(top)
        self.stack=QStackedWidget(); layout.addWidget(self.stack,1); outer.addWidget(body,1)
        self.pages=[]
        for name in PAGES:
            content=QWidget(); page=QVBoxLayout(content); page.setContentsMargins(0,8,0,10)
            page.addWidget(label(name,"pageTitle")); scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content)
            self.stack.addWidget(scroll); self.pages.append(page)
        self._build_dashboard(); self._build_editor(); self._build_data(); self._build_research(); self._build_paper(); self._build_brokers(); self._build_runs()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex); self.nav.setCurrentRow(0)
        for index in range(7): QShortcut(QKeySequence(f"Alt+{index+1}"),self,activated=lambda i=index:self.nav.setCurrentRow(i))
        QShortcut(QKeySequence.StandardKey.Open,self,activated=self.open_document)
        QShortcut(QKeySequence.StandardKey.Save,self,activated=self.save_document)
        self.statusBar().showMessage("就绪 · 选择 run JSON，或创建隔离的合成演示")
        self._refresh_capabilities(); self._refresh_jobs(); self._update_actions()

    def _table(self,name):
        table=DataTable(name,self.settings); self.tables.append(table); return table

    def _button(self,text,callback,primary=False):
        button=QPushButton(text); button.clicked.connect(lambda checked=False: callback())
        if primary: button.setObjectName("primaryButton")
        return button

    def _row(self,*widgets):
        box=QHBoxLayout()
        for widget in widgets: box.addWidget(widget)
        return box

    def _build_dashboard(self):
        page=self.pages[0]; page.addWidget(label("同一策略，从数据预检到回测与纸上执行。模式切换不启动任务。","pageSubtitle"))
        self.demo_button=self._button("创建合成演示",lambda:self.start_action("demo"),True)
        page.addLayout(self._row(self.demo_button,self._button("打开 run JSON",self.open_document),self._button("选择私有目录",self.choose_catalog)))
        self.overview=label("尚无运行。演示会创建虚构数据、独立配置和账户，输出保存在本工作台目录。","detailText"); page.addWidget(self.overview)
        page.addWidget(label("最近运行","brandTitle")); self.recent=self._table("最近运行"); page.addWidget(self.recent,1)
        self.recent.view.doubleClicked.connect(self._open_job_report)
        page.addWidget(label("待处理：真实券商未配置；旧整套策略需兼容报告；UNKNOWN 必须查询对账。","subtleText"))

    def _build_editor(self):
        page=self.pages[1]; page.addWidget(label("表单与 JSON 使用同一模型；未知字段保留并报告，不会静默丢弃。","pageSubtitle"))
        self.open_button=self._button("打开配置",self.open_document)
        self.save_button=self._button("保存副本",self.save_document,True)
        self.dirty_badge=label("未打开配置","statusPill")
        page.addLayout(self._row(self.open_button,self.save_button,self._button("选择目录",self.choose_catalog),self.dirty_badge))
        split=QSplitter(); split.setChildrenCollapsible(False)
        self.catalog=QListWidget(); self.catalog.setMinimumWidth(220); self.catalog.setWordWrap(False); self.catalog.setTextElideMode(Qt.TextElideMode.ElideRight); self.catalog.itemClicked.connect(self._catalog_selected); split.addWidget(self.catalog)
        self.editor_tabs=QTabWidget(); self.form_scroll=QScrollArea(); self.form_scroll.setWidgetResizable(True)
        self.form_widget=QWidget(); self.form_layout=QFormLayout(self.form_widget); self.form_scroll.setWidget(self.form_widget)
        self.editor_tabs.addTab(self.form_scroll,"表单")
        self.json_edit=QPlainTextEdit(); self.json_edit.setAccessibleName("配置 JSON"); self.json_edit.textChanged.connect(self._json_changed)
        self.editor_tabs.addTab(self.json_edit,"JSON"); split.addWidget(self.editor_tabs)
        inspector=QWidget(); right=QVBoxLayout(inspector); right.setContentsMargins(6,0,0,0)
        right.addWidget(label("校验与依赖","brandTitle")); self.issues=QPlainTextEdit(); self.issues.setReadOnly(True); self.issues.setMinimumWidth(150)
        right.addWidget(self.issues); split.addWidget(inspector); split.setSizes([170,590,260]); page.addWidget(split,1)
        self.editor_split=split

    def _build_data(self):
        page=self.pages[2]; page.addWidget(label("预检使用显式历史快照与 available_at；不会下载或改写本地数据。","pageSubtitle"))
        self.run_input=QLineEdit(); self.run_input.setReadOnly(True); self.run_input.setPlaceholderText("选择已保存的 run JSON")
        page.addLayout(self._row(self.run_input,self._button("选择 run",self.open_document)))
        self.timeline=QLineEdit(); self.timeline.setPlaceholderText("执行日历 timeline.json（历史模拟）")
        self.execution=QLineEdit(); self.execution.setPlaceholderText("独立报价 execution.json（计划 / 单步模拟）")
        self.decision_at=QLineEdit("2024-05-01T09:00:00+09:00"); self.now=QLineEdit("2024-05-01T09:00:00+09:00")
        form=QFormLayout(); form.addRow("执行日历",self._path_widget(self.timeline)); form.addRow("执行报价",self._path_widget(self.execution)); form.addRow("决策时间（含时区）",self.decision_at); form.addRow("执行时间（含时区）",self.now); page.addLayout(form)
        for edit in (self.timeline,self.execution,self.decision_at,self.now): edit.textChanged.connect(self.invalidate_preflight)
        self.preflight_button=self._button("运行数据与配置预检",lambda:self.start_action("preflight"),True); page.addWidget(self.preflight_button)
        self.preflight_status=label("尚未预检。修改任一输入后，原预检自动失效。","detailText"); page.addWidget(self.preflight_status)
        self.data_table=self._table("数据覆盖"); page.addWidget(self.data_table,1)

    def _path_widget(self,edit):
        widget=QWidget(); layout=QHBoxLayout(widget); layout.setContentsMargins(0,0,0,0); layout.addWidget(edit)
        button=self._button("浏览",lambda:self._pick_path(edit)); layout.addWidget(button); return widget

    def _pick_path(self,edit):
        path,_=QFileDialog.getOpenFileName(self,"选择本地输入","","JSON (*.json)")
        if path: edit.setText(path)

    def _build_research(self):
        page=self.pages[3]; page.addWidget(label("选择策略 → 数据预检 → 固定报价模拟 → 解释结果。所有运行保留配置快照。","pageSubtitle"))
        self.history_button=self._button("运行回测模拟",lambda:self.start_action("history"),True)
        self.cancel_button=self._button("取消本任务",self.cancel_job)
        page.addLayout(self._row(self.history_button,self.cancel_button,self._button("打开结果",self.open_report),self._button("比较运行",self.compare_reports)))
        self.assumptions=label("模型：fictional_fixed_quote_matching_v1；费用取 run.fees。基准未提供时不绘制；该结果不代表真实成交。","detailText"); page.addWidget(self.assumptions)
        self.nav_chart=SeriesChart("净值 / 基准"); self.drawdown_chart=SeriesChart("回撤",True); page.addWidget(self.nav_chart); page.addWidget(self.drawdown_chart)
        self.result_summary=label("费用、换手及方法限制将在完成后显示。","subtleText"); page.addWidget(self.result_summary)
        tabs=QTabWidget(); self.target_table=self._table("目标与风险"); self.trades_table=self._table("交易"); self.factor_table=self._table("因子诊断"); self.compare_table=self._table("运行比较")
        for title,table in (("原始目标 → 风险 → 订单",self.target_table),("交易",self.trades_table),("因子诊断",self.factor_table),("运行比较",self.compare_table)): tabs.addTab(table,title)
        tabs.setMinimumHeight(260); page.addWidget(tabs)

    def _build_paper(self):
        page=self.pages[4]; page.addWidget(label("独立模拟账户；计划、模拟执行与只读查询分别操作。不会使用现有生产 paper 账本。","pageSubtitle"))
        self.plan_button=self._button("生成计划",lambda:self.start_action("plan"),True)
        self.simulate_button=self._button("执行独立模拟",lambda:self.start_action("simulate"))
        self.journal_input=QLineEdit(); self.journal_input.setPlaceholderText("选择 v2 journal.sqlite（只读）")
        self.query_button=self._button("查询账本 / 恢复状态",self.query_journal)
        page.addLayout(self._row(self.plan_button,self.simulate_button)); page.addLayout(self._row(self.journal_input,self._button("选择账本",self.pick_journal),self.query_button))
        self.paper_summary=label("尚未查询账户。UNKNOWN 将阻止新执行并提示查询；界面没有重发入口。","detailText"); page.addWidget(self.paper_summary)
        tabs=QTabWidget(); self.positions=self._table("当前仓位"); self.orders=self._table("订单"); self.events=self._table("事件"); self.fills=self._table("成交")
        for title,table in (("仓位",self.positions),("订单与阻断",self.orders),("事件",self.events),("成交",self.fills)): tabs.addTab(table,title)
        page.addWidget(tabs,1); self.event_detail=QPlainTextEdit(); self.event_detail.setReadOnly(True); self.event_detail.setPlaceholderText("选择事件查看完整明细"); self.event_detail.setMaximumHeight(130); page.addWidget(self.event_detail)
        self.events.view.clicked.connect(lambda idx:self.event_detail.setPlainText(json.dumps(self._selected_row(self.events,idx),ensure_ascii=False,indent=2)))
        self.recovery_button=self._button("恢复执行（依赖未就绪）",lambda:None); self.recovery_button.setEnabled(False)
        self.recovery_button.setToolTip("真实查单 / 账户重同步及端到端恢复服务尚未完成；仅提供只读诊断")
        page.addWidget(self.recovery_button); self.paper_blocked=False

    def _build_brokers(self):
        page=self.pages[5]; page.addWidget(label("连接不等于可交易。协议 mock、本机集成与真实账户状态分别显示。","pageSubtitle"))
        self.broker_table=self._table("券商能力"); page.addWidget(self.broker_table,1)
        page.addWidget(self._button("刷新本地能力说明",self._refresh_capabilities))
        page.addWidget(label("Excel：专用工作簿、插件、COM 端口及查询能力均需独立验证。当前不访问 Excel、凭证或真实账户。","detailText"))
        blocked=self._button("连接真实账户（本轮未启用）",lambda:None); blocked.setEnabled(False); page.addWidget(blocked)

    def _build_runs(self):
        page=self.pages[6]; page.addWidget(label("每项任务有请求身份、不可变配置快照、PID、输出和退出码。取消仅处理本工作台持有的进程。","pageSubtitle"))
        self.run_table=self._table("任务记录"); page.addWidget(self.run_table,1)
        self.run_table.view.doubleClicked.connect(self._open_job_report)
        page.addLayout(self._row(self._button("打开结果文件",self.open_report),self._button("取消当前任务",self.cancel_job)))
        self.logs=QPlainTextEdit(); self.logs.setReadOnly(True); self.logs.setMaximumBlockCount(2000); self.logs.setMinimumHeight(150); page.addWidget(self.logs)

    def choose_catalog(self):
        directory=QFileDialog.getExistingDirectory(self,"选择独立策略目录",str(self.workspace))
        if directory: self.load_catalog(directory)

    def load_catalog(self,directory):
        self.catalog_rows=self.service.catalog(directory); self.catalog.clear()
        for row in self.catalog_rows:
            item=QListWidgetItem(row.get('display_name') or row.get('id',Path(row['path']).stem))
            item.setToolTip(f"{row.get('kind','?')} · v{row.get('version','?')}\n{row['path']}")
            item.setData(Qt.ItemDataRole.UserRole,row["path"]); self.catalog.addItem(item)

    def _catalog_selected(self,item): self.load_document(item.data(Qt.ItemDataRole.UserRole))

    def open_document(self):
        path,_=QFileDialog.getOpenFileName(self,"打开声明式配置","","JSON (*.json)")
        if path: self.load_document(path)

    def _confirm_unsaved(self,choice=None):
        if not self.document.dirty and not self.json_invalid and not self.form_errors: return True
        if choice is None:
            response=QMessageBox.question(self,"未保存修改","保存副本后继续，还是丢弃修改？",QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
            choice={QMessageBox.StandardButton.Save:"save",QMessageBox.StandardButton.Discard:"discard"}.get(response,"cancel")
        if choice=="cancel": return False
        if choice=="save": return self.save_document()
        return choice=="discard"

    def load_document(self,path,choice=None):
        if self.jobs.busy or not self._confirm_unsaved(choice): return False
        try:
            compatibility=self.service.compatibility(path)
            doc=ConfigDocument(path); self.document=doc; self.document_path=Path(path).resolve()
            self.json_invalid=False; self.form_errors={}; self._refresh_editor(); self.invalidate_preflight()
            if doc.data.get("kind")=="run":
                self.run_path=self.document_path; self.run_input.setText(str(self.run_path))
                index=self.mode.findData(doc.data.get("mode","backtest")); self.mode.setCurrentIndex(max(0,index))
                for edit,name in ((self.timeline,"timeline.json"),(self.execution,"execution.json")):
                    candidate=self.run_path.parent/name; edit.setText(str(candidate) if candidate.is_file() else "")
                date=doc.data.get("clock",{}).get("start")
                if date: self.decision_at.setText(date+"T09:00:00+09:00"); self.now.setText(date+"T09:00:00+09:00")
                self.strategy_badge.setText(f"策略引用：{doc.data.get('strategy','—')} · run v{doc.data.get('version','—')}")
                self.account_badge.setText("账户配置："+str(doc.data.get("account_ref","—")))
            if compatibility.get("conversion_required"):
                self.run_path=None; self.run_input.clear()
                self.issues.setPlainText("旧配置不能运行：需显式转换并重新审阅。\n"+json.dumps(compatibility,ensure_ascii=False,indent=2))
            self.nav.setCurrentRow(1); self._update_actions(); return True
        except Exception as exc:
            self.issues.setPlainText(str(exc)); self.statusBar().showMessage("配置未打开；原选择保留"); return False

    def _refresh_editor(self):
        with QSignalBlocker(self.json_edit): self.json_edit.setPlainText(self.document.text)
        self._refresh_form(); self._show_issues()

    def _refresh_form(self):
        while self.form_layout.rowCount(): self.form_layout.removeRow(0)
        self.fields={}
        def visit(value,prefix=""):
            for key,item in value.items():
                path=f"{prefix}.{key}" if prefix else key
                if isinstance(item,dict) and item:
                    heading=label(path,"brandTitle"); self.form_layout.addRow(heading); visit(item,path)
                else:
                    edit=QLineEdit(item if isinstance(item,str) else json.dumps(item,ensure_ascii=False)); edit.setAccessibleName(path); edit.setToolTip("字段："+path)
                    edit.editingFinished.connect(lambda p=path,e=edit,old=item:self._field_changed(p,e,old))
                    self.fields[path]=edit; self.form_layout.addRow(path.rsplit(".",1)[-1],edit)
        visit(self.document.data); self.form_widget.setEnabled(not self.json_invalid and not self.jobs.busy)

    def _field_changed(self,path,edit,old):
        try:
            value=edit.text() if isinstance(old,str) else json.loads(edit.text())
            self.document.set_field(path,value); self.form_errors.pop(path,None)
            with QSignalBlocker(self.json_edit): self.json_edit.setPlainText(self.document.text)
        except Exception as exc: self.form_errors[path]=str(exc)
        edit.setProperty("invalid",path in self.form_errors); edit.style().unpolish(edit); edit.style().polish(edit)
        self.invalidate_preflight(); self._show_issues()

    def _json_changed(self):
        try:
            self.document.set_json(self.json_edit.toPlainText()); self.json_invalid=False; self.form_errors={}; self._refresh_form()
        except Exception as exc:
            self.json_invalid=True; self.form_widget.setEnabled(False); self.issues.setPlainText("JSON："+str(exc))
        self.invalidate_preflight(); self._show_issues()

    def _show_issues(self):
        if not self.json_invalid:
            issues=self.document.validate(); lines=[f"{i.get('field','配置')}：{i.get('message',str(i))}" for i in issues]
            lines.extend(f"{k}：{v}" for k,v in self.form_errors.items())
            data=self.document.data; refs={k:data[k] for k in ("strategy","factors","universe","implementation","data_snapshot","account_ref") if k in data}
            self.issues.setPlainText(("\n".join(lines) if lines else "结构校验通过；run 的完整引用需数据预检。")+"\n\n依赖 / 有效配置\n"+json.dumps(refs,ensure_ascii=False,indent=2)+f"\n\n编辑版本：{self.document.revision}")
        dirty=self.document.dirty or self.json_invalid or bool(self.form_errors)
        self.dirty_badge.setText("● 未保存修改" if dirty else "已保存 / 无修改")
        self._update_actions()

    def save_document(self,destination=None):
        if self.jobs.busy or self.json_invalid or self.form_errors: return False
        if destination is None:
            proposed=str((self.document_path or self.workspace/"strategy.json").with_stem((self.document_path.stem if self.document_path else "strategy")+"_edited"))
            destination,_=QFileDialog.getSaveFileName(self,"保存配置副本（引用按新目录解析）",proposed,"JSON (*.json)")
        if not destination: return False
        try:
            self.document.save_as(destination); self.document_path=Path(destination).resolve(); self._show_issues(); self.invalidate_preflight()
            if self.document.data.get("kind")=="run": self.run_path=self.document_path; self.run_input.setText(str(self.run_path))
            self.statusBar().showMessage("配置已保存；运行前重新预检"); return True
        except Exception as exc: self.issues.setPlainText(str(exc)); return False

    def invalidate_preflight(self,*_):
        self.preflight_result=None
        if hasattr(self,"preflight_status"): self.preflight_status.setText("预检已失效 / 尚未预检；请重新检查当前输入。")
        if hasattr(self,"history_button"): self._update_actions()

    def _mode_changed(self): self.invalidate_preflight()

    def _request(self,action):
        request={"action":action,"mode":self.mode.currentData(),"run_path":str(self.run_path) if self.run_path else None,
            "timeline_path":self.timeline.text() or None,"execution_path":self.execution.text() or None,
            "decision_at":self.decision_at.text(),"now":self.now.text()}
        if self.preflight_result and action in {"history","plan","simulate"}: request["expected_fingerprint"]=self.preflight_result.get("fingerprint")
        return request

    def start_action(self,action):
        if self.jobs.busy: return False
        if action not in {"demo","journal"}:
            if not self.run_path or self.document.dirty or self.json_invalid or self.form_errors: return False
            if self.mode.currentData()=="broker": return False
            if action!="preflight" and (not self.preflight_result or not self.preflight_result.get("ok")): return False
            if action=="simulate" and self.paper_blocked: return False
        try:
            self.jobs.start(self._request(action)); self._update_actions(); return True
        except Exception as exc: self.statusBar().showMessage(str(exc)); return False

    def _update_actions(self):
        if not hasattr(self,"history_button"): return
        busy=self.jobs.busy; clean=not(self.document.dirty or self.json_invalid or self.form_errors)
        ready=bool(self.run_path and clean and self.preflight_result and self.preflight_result.get("ok")) and self.mode.currentData()!="broker"
        self.demo_button.setEnabled(not busy); self.open_button.setEnabled(not busy); self.save_button.setEnabled(not busy and not self.json_invalid)
        self.mode.setEnabled(not busy); self.catalog.setEnabled(not busy); self.editor_tabs.setEnabled(not busy)
        for edit in (self.timeline,self.execution,self.decision_at,self.now): edit.setEnabled(not busy)
        self.preflight_button.setEnabled(not busy and bool(self.run_path) and clean and self.mode.currentData()!="broker")
        self.history_button.setEnabled(not busy and ready and bool(self.timeline.text()) and self.mode.currentData()=="backtest")
        self.plan_button.setEnabled(not busy and ready and bool(self.execution.text()))
        self.simulate_button.setEnabled(not busy and ready and bool(self.execution.text()) and self.mode.currentData() in {"paper","fake"} and not self.paper_blocked)
        self.query_button.setEnabled(not busy); self.cancel_button.setEnabled(busy)

    def cancel_job(self):
        if self.jobs.cancel(): self.statusBar().showMessage("正在取消本工作台持有的进程；保留日志和不完整输出")

    def _job_started(self,job):
        self.statusBar().showMessage(f"运行中 · {job['action']} · PID {job['pid']}"); self._refresh_jobs()

    def _job_log(self,text):
        if not text.startswith("WORKBENCH_RESULT="): self.logs.appendPlainText(text[-4000:])

    def _job_finished(self,job):
        self.statusBar().showMessage(f"{job['status']} · {job['action']} · 退出码 {job.get('exit_code')}")
        envelope=job.get("result") or {}; result=envelope.get("result") or {}
        if job["status"]=="COMPLETED":
            action=job["action"]
            if action=="preflight":
                self.preflight_result=result; self.preflight_status.setText("预检通过 · 输入身份 "+str(result.get("fingerprint",""))[:16] if result.get("ok") else json.dumps(result.get("issues",[]),ensure_ascii=False))
                rows=result.get("datasets",[])
                if isinstance(rows,dict): rows=[{"dataset":k,**(v if isinstance(v,dict) else {"value":v})} for k,v in rows.items()]
                self.data_table.set_rows(rows); self.cutoff_badge.setText("数据截止："+str(result.get("cutoff",self.decision_at.text())))
                self.strategy_badge.setText("策略："+str(result.get("strategy_id",result.get("strategy_hash","")))+" · "+str(result.get("strategy_version","")))
                if result.get("account_id"): self.account_badge.setText("模拟账户："+str(result["account_id"]))
            elif action=="journal": self.show_journal(result)
            elif action=="demo":
                root=Path(result.get("directory",result.get("output_dir",job["output_dir"])))
                if not (root/"backtest.json").is_file():
                    matches=list(Path(job["output_dir"]).rglob("backtest.json")); root=matches[0].parent if matches else root
                if (root/"backtest.json").is_file(): self.load_catalog(root); self.load_document(root/"backtest.json",choice="discard"); self.nav.setCurrentRow(2)
                self.overview.setText("合成演示已创建。先检查数据，再选择回测或独立 Paper 模拟。")
            else:
                report=result.get("report",result.get("document",result))
                if isinstance(report,dict) and ("decisions" in report or "plan" in report): self.show_report(report)
                for artifact in envelope.get("artifacts",[]):
                    path=artifact.get("path") if isinstance(artifact,dict) else artifact
                    if path and str(path).endswith(".json") and Path(path).is_file():
                        try:
                            document=self._read_report(path)
                            if "decisions" in document or "plan" in document: self.show_report(document)
                        except (ValueError,OSError): pass
        else:
            if job["action"]=="preflight": self.preflight_result=None
            error=json.dumps(envelope.get("errors",job.get("error")),ensure_ascii=False)
            self.logs.appendPlainText(error); self.preflight_status.setText("任务未通过："+error[:800])
        self._refresh_jobs(); self._update_actions()

    def _refresh_jobs(self):
        rows=[{k:j.get(k,"") for k in ("job_id","action","status","pid","exit_code","started_at","output_dir")} for j in reversed(self.jobs.jobs)]
        self.run_table.set_rows(rows); self.recent.set_rows(rows[:10])

    def _selected_row(self,table,index):
        source=table.proxy.mapToSource(index).row()
        return table.rows[source] if 0<=source<len(table.rows) else {}

    def _open_job_report(self,index):
        table=self.run_table if self.sender() is self.run_table.view else self.recent
        row=self._selected_row(table,index); root=Path(row.get("output_dir",""))
        if root.is_dir():
            for path in root.rglob("*.json"):
                try:
                    value=self._read_report(path)
                    if "decisions" in value or "plan" in value: self.show_report(value); self.nav.setCurrentRow(3); return
                except (ValueError,OSError): continue

    def open_report(self):
        path,_=QFileDialog.getOpenFileName(self,"打开本地结果","","JSON (*.json)")
        if path:
            try: self.show_report(self._read_report(path))
            except Exception as exc: self.statusBar().showMessage(str(exc))

    def _read_report(self,path):
        path=Path(path); report=json.loads(path.read_text(encoding="utf-8"))
        for root in (path.parent,path.parent.parent):
            manifest_path=root/"inputs"/"workbench_snapshot.json"
            if not manifest_path.is_file(): continue
            manifest=json.loads(manifest_path.read_text(encoding="utf-8")); configs={}
            for file,digest in manifest.get("copied_hashes",{}).items():
                candidate=Path(file)
                if not candidate.is_relative_to(manifest_path.parent): continue
                raw=candidate.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=digest: raise ValueError("运行快照已改变，无法可信比较")
                if candidate.suffix.lower() != ".json": continue
                value=json.loads(raw)
                if value.get("kind") in {"run","strategy","factor"}:
                    configs[value["kind"]+":"+value.get("id",candidate.stem)]=value
            report={**report,"workbench_configs":configs}; break
        return report

    def show_report(self,report):
        self.report=report; nav=report.get("nav",[])
        self.nav_chart.set_series([r["at"] for r in nav],[("策略净值",[r["nav"] for r in nav])] if nav else [])
        self.drawdown_chart.set_series([r["at"] for r in nav],[("策略回撤",[r["drawdown"] for r in nav])] if nav else [])
        decisions=report.get("decisions",[report] if "plan" in report else [])
        target_rows=[]; factor_rows=[]; intents=[]
        for number,decision in enumerate(decisions):
            risk=decision.get("risk",{}); plan=decision.get("plan",{}); raw={p["code"]:p["weight"] for p in (risk.get("raw") or {}).get("positions",[])}
            allowed={p["code"]:p["weight"] for p in (risk.get("allowed") or {}).get("positions",[])}
            orders={p["code"]:p for p in plan.get("intents",[])}; intents.extend(plan.get("intents",[]))
            for code in sorted(set(raw)|set(allowed)|set(orders)|set(plan.get("skipped",{}))):
                order=orders.get(code,{})
                target_rows.append({"期次":number+1,"代码":code,"原始权重":raw.get(code,0),"允许权重":allowed.get(code,0),
                    "方向":order.get("side","—"),"股数":order.get("quantity",0),"原因":plan.get("skipped",{}).get(code,[])+risk.get("reasons",[])})
            for name,diagnostic in decision.get("diagnostics",{}).get("factors",{}).items(): factor_rows.append({"期次":number+1,"因子":name,**diagnostic})
        self.target_table.set_rows(target_rows); self.factor_table.set_rows(factor_rows)
        journal=report.get("journal",report.get("execution",{}).get("view",{}))
        fills=[json.loads(r["payload"]) if isinstance(r.get("payload"),str) else r for r in journal.get("fills",[])]
        self.trades_table.set_rows(fills or intents)
        fees=sum((Decimal(str(row.get("fee",0))) for row in fills),Decimal(0))
        turnover=[f"{Decimal(str(d.get('plan',{}).get('estimated_turnover',0))):.2%}" for d in decisions]
        self.result_summary.setText(f"{len(decisions)} 次决策 · {len(intents)} 笔计划 · {len(fills)} 笔模拟成交 · 已成交费用 {fees:.2f}。逐期计划换手（成交额 / 权益）：{', '.join(turnover)}。基准未提供。")
        if report.get("execution",{}).get("journal"):
            self.journal_input.setText(report["execution"]["journal"])
        if self.mode.currentData() in {"paper","fake"}: self.nav.setCurrentRow(4)
        else: self.nav.setCurrentRow(3)

    def compare_reports(self,other=None):
        if self.report is None: self.statusBar().showMessage("先打开一个结果"); return
        if other is None:
            path,_=QFileDialog.getOpenFileName(self,"选择对比结果","","JSON (*.json)")
            if not path: return
            other=self._read_report(path)
        rows=[]
        for key in ("strategy_hash","data_snapshot_hash","execution_timeline_hash","mode","model","file_hashes"):
            left=self.report.get(key,self.report.get("evidence",{}).get(key)); right=other.get(key,other.get("evidence",{}).get(key))
            rows.append({"维度":key,"当前":left,"对比":right,"一致":left==right})
        def flatten(value,prefix=""):
            result={}
            for key,item in value.items():
                name=prefix+key
                if isinstance(item,dict): result.update(flatten(item,name+"."))
                else: result[name]=item
            return result
        left=flatten(self.report.get("workbench_configs",{})); right=flatten(other.get("workbench_configs",{}))
        for key in sorted(set(left)|set(right)):
            if left.get(key)!=right.get(key): rows.append({"维度":"配置."+key,"当前":left.get(key),"对比":right.get(key),"一致":False})
        if not left or not right: rows.append({"维度":"配置明细","当前":"缺少可验证的工作台输入快照时，仅比较结果中的身份字段","一致":False})
        self.compare_table.set_rows(rows)

    def pick_journal(self):
        path,_=QFileDialog.getOpenFileName(self,"只读选择 v2 账本","","SQLite (*.sqlite *.db)")
        if path: self.journal_input.setText(path)

    def query_journal(self):
        if self.jobs.busy or not self.journal_input.text(): return False
        request=self._request("journal"); request["journal_path"]=self.journal_input.text()
        self.jobs.start(request); self._update_actions(); return True

    def show_journal(self,value):
        self.positions.set_rows(value.get("positions",[])); self.orders.set_rows(value.get("orders",[]))
        self.events.set_rows(value.get("events",[])); self.fills.set_rows(value.get("fills",[]))
        blockers=value.get("blockers",[]); self.paper_blocked=bool(blockers)
        accounts=[]
        for row in value.get("accounts",[]):
            accounts.append(f"账户 {row.get('account_id','—')} · 权益 {Decimal(str(row.get('equity',0))):,.2f} · 可用现金 {Decimal(str(row.get('available_cash',0))):,.2f} · 版本 {row.get('revision','—')}")
        self.paper_summary.setText(("\n".join(accounts) or "无账户记录")+"\n"+("阻断："+json.dumps(blockers,ensure_ascii=False) if blockers else "未发现 UNKNOWN / 对账阻断；查询不代表允许真实下单。"))
        self._update_actions()

    def _refresh_capabilities(self):
        rows=self.service.broker_capabilities()
        if isinstance(rows,dict): rows=rows.get("brokers",[{"broker":k,**v} for k,v in rows.items() if isinstance(v,dict)])
        display=[]
        for row in rows:
            name=row.get("broker",""); excel=name in {"rakuten","neotrade"}
            display.append({"券商":name,"协议模拟":"VBA 映射 Mock" if excel else "API 映射 Mock",
                "本机集成":"COM 端口未实现" if excel else "未验证 · 无默认连接",
                "真实账户":"未验证 · 已禁用","查单 / 成交":"缺失 · 不可恢复" if excel else "仅映射 / 原始订单明细",
                "依据":row.get("source","")})
        self.broker_table.set_rows(display)

    def show_help(self):
        QMessageBox.information(self,"设置与帮助",f"工作台目录：{self.workspace}\n表格支持筛选、排序、Ctrl+C、CSV 导出，列宽保存在此目录 ui.ini。\nAlt+1…7 切页，Ctrl+O 打开，Ctrl+S 保存副本。\n运行前预检；修改输入会撤销预检。运行期间配置锁定。\n取消只终止本工作台拥有的子进程。UNKNOWN 先查询，无盲重发。\n旧策略 / 完整恢复 / Excel 查询未迁移时明确阻断。无调度，无真实账户连接。")

    def closeEvent(self,event):
        if self.jobs.busy:
            answer=QMessageBox.question(self,"仍有本工作台任务","取消本任务后关闭？",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes: event.ignore(); return
            self.jobs.cancel(); event.ignore(); self.jobs.finished.connect(lambda _:self.close()); return
        if not self._confirm_unsaved(): event.ignore(); return
        for table in self.tables: table.persist()
        self.settings.sync(); event.accept()

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--workspace",type=Path,default=Path(__file__).resolve().parents[1]/"output"/"kabuforge_workspace"); parser.add_argument("--run",type=Path)
    parser.add_argument("--record-dir",type=Path,help="Opt-in app-window recording; Ctrl+Shift+R toggles")
    args=parser.parse_args(argv)
    if os.name=="nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KabuForge.Workbench")
    app=QApplication.instance() or QApplication(sys.argv[:1])
    from .product_ui import ProductWorkbench
    app.setApplicationName("KabuForge"); window=ProductWorkbench(args.workspace)
    if args.run: window.load_catalog(args.run.parent); window.load_document(args.run)
    if args.record_dir:
        from .window_recording import WindowRecorder
        window.recorder=WindowRecorder(window,args.record_dir)
    window.show(); return app.exec()

if __name__=="__main__": raise SystemExit(main())
