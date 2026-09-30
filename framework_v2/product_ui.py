"""User-facing KabuForge shell over the existing isolated execution workbench."""
from __future__ import annotations
import json,uuid
from pathlib import Path
from PySide6.QtCore import Qt,QSignalBlocker,QTimer
from PySide6.QtGui import QKeySequence,QShortcut,QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
    QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QGroupBox,QFileDialog,QMessageBox,QSizePolicy)
from .workbench_qt import WorkbenchWindow
from .workbench_widgets import label
from .i18n import Translator,LANGUAGES,tr
from .guided_strategy import parse_sentence
from .help_viewer import HelpDialog
from .brand_theme import BRAND_DIR,branded_stylesheet,DARK

class ProductWorkbench(WorkbenchWindow):
    def __init__(self,workspace,service=None):
        self.translator=Translator(); self.guide_recipe=None; self.market_manifest=None; self.auto_history=False
        self.help_dialog=None; self.product_ready=False; self._table_versions={}
        super().__init__(workspace,service)
        assets=(Path(__file__).parent/"assets").as_posix()
        self.setStyleSheet(branded_stylesheet(self.styleSheet())+f'''QComboBox::down-arrow,QDateEdit::down-arrow {{image:url("{assets}/chevron_down.svg");width:12px;height:8px;}}
            QSpinBox::up-arrow,QDoubleSpinBox::up-arrow {{image:url("{assets}/chevron_up.svg");width:10px;height:6px;}}
            QSpinBox::down-arrow,QDoubleSpinBox::down-arrow {{image:url("{assets}/chevron_down.svg");width:10px;height:6px;}}
            QSpinBox::up-button,QDoubleSpinBox::up-button {{width:22px;border:0;}}
            QSpinBox::down-button,QDoubleSpinBox::down-button {{width:22px;border:0;}}
            QComboBox {{padding-right:28px;}}''')
        self.mode.setMinimumWidth(270)
        self.language=str(self.settings.value("language","zh_CN"))
        if self.language not in LANGUAGES: self.language="zh_CN"
        self.setWindowTitle("KabuForge · "+tr("日本股票策略研究工作台",self.language))
        from PySide6.QtWidgets import QApplication
        icon=QIcon(str(BRAND_DIR/"app-icon.svg"))
        self.setWindowIcon(icon); QApplication.instance().setWindowIcon(icon)
        rail=self.findChild(QWidget,"sideRail"); rail.setFixedWidth(225)
        for widget in rail.findChildren(QLabel):
            if widget.text() in {"PRIVATE ENGINE","量化工作台"}: widget.hide()
        self.brand_logo=QSvgWidget(str(BRAND_DIR/"logo-horizontal-dark.svg"))
        self.brand_logo.setFixedSize(190,41); self.brand_logo.setAccessibleName("KabuForge")
        self.brand_logo.setStyleSheet("background:transparent;")
        rail.layout().insertWidget(0,self.brand_logo)
        self.nav_chart.brand_palette=DARK; self.drawdown_chart.brand_palette=DARK
        # The header language selector is independent of the execution-mode selector.
        top=self.mode.parentWidget().layout().itemAt(0).layout()
        self.language_picker=QComboBox(); self.language_picker.setProperty("ownTranslation",True)
        for code,title in LANGUAGES.items(): self.language_picker.addItem(title,code)
        self.language_picker.setCurrentIndex(self.language_picker.findData(self.language))
        self.language_picker.setAccessibleName("Language / 言語 / 语言")
        top.addWidget(self.language_picker,0,2)
        self.language_picker.currentIndexChanged.connect(lambda:self.set_language(self.language_picker.currentData()))
        for i,name in enumerate(["首页","我的策略","数据中心","回测结果","纸上交易","券商连接","运行记录"]):
            self.nav.item(i).setText(name)
            self.pages[i].itemAt(0).widget().setText(name)
        self.strategy_badge.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.strategy_badge.setToolTip(self.strategy_badge.text())
        self.account_badge.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.help_button.setText("操作手册")
        QShortcut(QKeySequence("F1"),self,activated=self.show_help)
        self.product_ready=True
        self._refresh_library()
        self.history_button.clicked.disconnect()
        self.history_button.clicked.connect(lambda:self.run_guided() if self.guide_recipe else self.start_action("history"))
        self.nav.currentRowChanged.connect(lambda *_:self.localize())
        self.jobs.started.connect(lambda *_:self.localize())
        self.jobs.finished.connect(lambda *_:self.localize())
        self.mode.currentIndexChanged.connect(lambda *_:self.localize())
        self.statusBar().showMessage("KabuForge")
        saved=self.settings.value("market_manifest","")
        if saved and Path(str(saved)).is_file(): self._market_ready(str(saved))
        self.set_language(self.language)
        QShortcut(QKeySequence("Ctrl+Shift+D"),self,activated=self.open_data_diagnostics)
        QShortcut(QKeySequence("Ctrl+Return"),self,activated=self.preflight_button.click)
        QShortcut(QKeySequence("Ctrl+Shift+Return"),self,activated=self.history_button.click)
        QShortcut(QKeySequence("Ctrl+Shift+L"),self,activated=lambda:
                  self.language_picker.setCurrentIndex((self.language_picker.currentIndex()+1)%self.language_picker.count()))
        QShortcut(QKeySequence("Ctrl+Shift+O"),self,activated=self.open_report)

    def open_data_diagnostics(self):
        self.nav.setCurrentRow(2)
        self.data_advanced.setChecked(True)
        self.timeline.setFocus()

    def text(self,zh,ja,en):
        return {"zh_CN":zh,"ja_JP":ja,"en_US":en}[getattr(self,"language","zh_CN")]

    def _build_dashboard(self):
        page=self.pages[0]
        page.addWidget(label("开始你的第一次研究","brandTitle"))
        page.addWidget(label("先体验，再连接自己的数据。所有策略与结果保存在本机。","pageSubtitle"))
        self.demo_button=self._button("1  体验离线演示",self.experience_demo,True)
        # Vertical onboarding keeps long translated labels readable at 820px.
        for button in (self.demo_button,self._button("2  连接与下载数据",lambda:self.nav.setCurrentRow(2)),self._button("3  创建我的策略",lambda:self.nav.setCurrentRow(1))):
            button.setMinimumHeight(42); page.addWidget(button)
        self.overview=label("尚无运行。先体验无需 API key 的合成数据演示，或到数据中心连接 J-Quants。","detailText"); page.addWidget(self.overview)
        page.addWidget(label("最近运行","brandTitle")); self.recent=self._table("最近运行"); page.addWidget(self.recent,1)
        self.recent.view.doubleClicked.connect(self._open_job_report)
        page.addWidget(label("演示使用虚构数据；不代表投资收益。真实数据下载后需选择价格研究模板。","subtleText"))

    def _build_editor(self):
        page=self.pages[1]
        library_row=QHBoxLayout(); self.library=QComboBox(); self.library.setMinimumWidth(0)
        self.library.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.library.setMinimumContentsLength(20); library_row.addWidget(self.library,1)
        library_row.addWidget(self._button("打开已保存策略",self.open_saved_strategy)); page.addLayout(library_row)
        self.guide_box=QGroupBox(); form=QFormLayout(self.guide_box)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.strategy_name=QLineEdit("My strategy"); self.strategy_name.setMaxLength(100)
        self.template=QComboBox(); self.template.addItem("质量与趋势（合成演示）","synthetic"); self.template.addItem("价格动量（下载数据）","market")
        self.holding_count=QSpinBox(); self.holding_count.setRange(1,5); self.holding_count.setValue(5)
        self.frequency=QComboBox()
        for title,key in (("每月","monthly"),("每周","weekly"),("每日","daily")): self.frequency.addItem(title,key)
        self.weighting=QComboBox(); self.weighting.addItem("等权","equal_weight")
        self.cash=QDoubleSpinBox(); self.cash.setRange(10000,1e10); self.cash.setDecimals(0); self.cash.setSingleStep(100000); self.cash.setValue(2000000)
        self.fee=QDoubleSpinBox(); self.fee.setRange(0,5); self.fee.setDecimals(3); self.fee.setValue(.1)
        self.quality=QSpinBox(); self.quality.setRange(0,100); self.quality.setValue(50)
        self.lookback=QSpinBox(); self.lookback.setRange(2,500); self.lookback.setValue(20)
        for title,widget in (("策略名称",self.strategy_name),("策略模板",self.template),("持仓数量",self.holding_count),
            ("调仓频率",self.frequency),("权重方式",self.weighting),("初始资金（JPY）",self.cash),
            ("费用（单边，%）",self.fee),("质量占比（%）",self.quality),("动量观察期（交易日）",self.lookback)):
            form.addRow(title,widget)
        self.lookback.setEnabled(False)
        self.sentence=QLineEdit(); self.sentence.setPlaceholderText("每月选5只股票，等权")
        self.parse_button=self._button("解析到表单",self.parse_input)
        sentence_box=QWidget(); row=QHBoxLayout(sentence_box); row.setContentsMargins(0,0,0,0); row.addWidget(self.sentence,1); row.addWidget(self.parse_button)
        form.addRow("用一句话辅助填写",sentence_box)
        form.addRow(label("本地解析只支持数量、频率、等权。其余条件请用表单设置；不会自动运行。","subtleText"))
        self.guide_summary=label("","detailText"); self.guide_summary.setProperty("ownTranslation",True); form.addRow(self.guide_summary)
        self.create_button=self._button("检查并创建策略",self.create_strategy,True)
        self.guided_run=self._button("开始回测",self.run_guided)
        form.addRow(self.create_button,self.guided_run); page.addWidget(self.guide_box)
        self.advanced_toggle=self._button("显示高级配置",self.toggle_advanced); page.addWidget(self.advanced_toggle)
        self.advanced_editor=QWidget(); advanced_layout=QVBoxLayout(self.advanced_editor)
        # Keep the proven config model and diagnostics available without leading with JSON.
        original=self.pages[1]; self.pages[1]=advanced_layout
        super()._build_editor(); self.pages[1]=original
        self.editor_tabs.setTabText(1,"高级 JSON")
        self.editor_split.widget(2).setVisible(False)
        self.editor_split.setStretchFactor(1,1); self.editor_split.setSizes([230,700,0])
        advanced_layout.addWidget(self._button("校验与依赖",lambda:self.editor_split.widget(2).setVisible(not self.editor_split.widget(2).isVisible())))
        page.addWidget(self.advanced_editor); self.advanced_editor.hide()
        self.template.currentIndexChanged.connect(self._template_changed)
        for widget in (self.strategy_name,self.sentence): widget.textChanged.connect(self._guide_changed)
        for widget in (self.holding_count,self.cash,self.fee,self.quality,self.lookback): widget.valueChanged.connect(self._guide_changed)
        self.frequency.currentIndexChanged.connect(self._guide_changed)
        page.addStretch()

    def _build_data(self):
        from .data_connection_qt import DataConnectionPanel
        page=self.pages[2]
        self.connection=DataConnectionPanel(self.workspace,language="zh_CN",parent=self)
        self.connection.setProperty("ownTranslation",True)
        self.connection.downloaded.connect(self._market_ready); page.addWidget(self.connection)
        self.market_pick=self._button("选择已下载的数据",self.pick_market); page.addWidget(self.market_pick)
        self.market_status=label("","detailText"); self.market_status.setProperty("ownTranslation",True); page.addWidget(self.market_status)
        self.data_advanced=QGroupBox("高级配置与诊断"); self.data_advanced.setCheckable(True); self.data_advanced.setChecked(False)
        box=QVBoxLayout(self.data_advanced); content=QWidget(); inner=QVBoxLayout(content)
        original=self.pages[2]; self.pages[2]=inner; super()._build_data(); self.pages[2]=original
        box.addWidget(content); content.hide(); self.data_advanced.toggled.connect(content.setVisible); page.addWidget(self.data_advanced)
        page.addStretch(1)
        self.market_status.hide()

    def _template_changed(self,*_):
        market=self.template.currentData()=="market"
        self.holding_count.setMaximum(100 if market else 5)
        self.quality.setEnabled(not market); self.lookback.setEnabled(market); self._guide_changed()

    def experience_demo(self):
        if self.jobs.busy: return False
        self.template.setCurrentIndex(0); self.holding_count.setValue(5)
        self.frequency.setCurrentIndex(0); self.quality.setValue(50)
        self.cash.setValue(2000000); self.fee.setValue(.1)
        return self.create_strategy()

    def _refresh_library(self):
        self.library.clear()
        for path in sorted((self.workspace/"strategies").glob("*.json"),reverse=True):
            try:
                saved=json.loads(path.read_text(encoding="utf-8"))
                self.library.addItem(saved["recipe"]["name"],str(path))
            except (OSError,ValueError,KeyError): continue

    def _save_recipe(self,recipe,run=None):
        path=self.workspace/"strategies"/("strategy_"+uuid.uuid4().hex[:12]+".json"); path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"recipe":recipe,"market_manifest":str(self.market_manifest) if self.market_manifest else None,"run":str(run) if run else None},ensure_ascii=False,indent=2),encoding="utf-8")
        self._refresh_library()

    def open_saved_strategy(self):
        if self.jobs.busy or not self.library.currentData() or not self._confirm_unsaved(): return False
        try:
            saved=json.loads(Path(self.library.currentData()).read_text(encoding="utf-8")); r=saved["recipe"]
            if r["template"]=="synthetic":
                if not self.load_document(saved["run"],choice="discard"): return False
                self.load_catalog(Path(saved["run"]).parent)
            else:
                from .data_connection import load_bars
                load_bars(saved["market_manifest"]); self._market_ready(saved["market_manifest"])
            self.template.setCurrentIndex(self.template.findData(r["template"])); self.strategy_name.setText(r["name"])
            self.holding_count.setValue(r["count"]); self.frequency.setCurrentIndex(self.frequency.findData(r["frequency"]))
            for key in ("cash","fee","quality","lookback"): getattr(self,key).setValue(r[key])
            self.guide_recipe=r; self._show_recipe(); self._update_actions(); return True
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.guide_summary.setText(self.text("无法打开策略：","戦略を開けません：","Cannot open strategy: ")+str(exc)); return False

    def _guide_changed(self,*_):
        self.guide_recipe=None
        if hasattr(self,"guided_run"): self.guided_run.setEnabled(False)
        if hasattr(self,"guide_summary") and self.product_ready:
            self.guide_summary.setText(self.text("参数已修改，请检查并创建策略。","設定を変更しました。確認して戦略を作成してください。","Settings changed. Review and create the strategy."))

    def recipe(self):
        return {"name":self.strategy_name.text().strip(),"template":self.template.currentData(),"count":self.holding_count.value(),
                "frequency":self.frequency.currentData(),"cash":self.cash.value(),"fee":self.fee.value(),
                "quality":self.quality.value(),"lookback":self.lookback.value(),"weighting":"equal_weight"}

    def parse_input(self):
        try:
            parsed=parse_sentence(self.sentence.text())
            if parsed["count"]>self.holding_count.maximum(): raise ValueError("count_out_of_range")
        except ValueError:
            self.guide_summary.setText(self.text("未应用：请使用示例句式，且数量不能超过模板上限。其他条件请使用表单。","適用しませんでした。例文の形式と銘柄数上限を確認し、他の条件はフォームで設定してください。","Not applied: use the example format and a count within the template limit. Set other conditions in the form.")); return False
        self.holding_count.setValue(parsed["count"]); self.frequency.setCurrentIndex(self.frequency.findData(parsed["frequency"]))
        self.guide_summary.setText(self.text("已填写数量和频率；请核对其他参数，再创建策略。","銘柄数と頻度を反映しました。他の設定を確認して作成してください。","Count and frequency filled. Check other settings before creating.")); return True

    def create_strategy(self):
        if self.jobs.busy: return False
        recipe=self.recipe()
        if not recipe["name"]:
            self.guide_summary.setText(self.text("请输入策略名称。","戦略名を入力してください。","Enter a strategy name.")); return False
        if not self._confirm_unsaved(): return False
        if recipe["template"]=="market":
            if not self.market_manifest:
                self.guide_summary.setText(self.text("请先下载数据，或选择已完成的下载清单。","先に取得するか、完了した清単を選択してください。","Download data first, or select a completed manifest.")); return False
            try:
                from .data_connection import load_bars
                bars=load_bars(self.market_manifest)
                if recipe["count"]>len({r["code"] for r in bars}): raise ValueError("Not enough stocks")
            except Exception as exc:
                self.guide_summary.setText(self.text("数据未就绪：","データ未準備：","Data not ready: ")+str(exc)); return False
            self._save_recipe(recipe)
            self.guide_recipe=recipe; self._show_recipe(); self._update_actions(); return True
        self.jobs.start({"action":"guided_demo","recipe":recipe,"mode":"backtest"}); self.pending_recipe=recipe; self._update_actions(); return True

    def _show_recipe(self):
        if not self.guide_recipe: return
        r=self.guide_recipe; freq=tr({"monthly":"每月","weekly":"每周","daily":"每日"}[r["frequency"]],self.language)
        self.guide_summary.setText(self.text(
            f"已创建：{r['name']} · {freq} · {r['count']} 只 · 等权 · {r['cash']:,.0f} JPY · 单边费用 {r['fee']}%。\n数据：{'下载数据（历史可见性未认证）' if r['template']=='market' else '虚构演示'}。确认后点击开始回测。",
            f"作成済み：{r['name']} · {freq} · {r['count']} 銘柄 · 均等配分 · {r['cash']:,.0f} JPY · 片道 {r['fee']}%。\nデータ：{'取得データ（過去の可視性は未認証）' if r['template']=='market' else '架空デモ'}。確認後にバックテストを開始してください。",
            f"Created: {r['name']} · {freq} · {r['count']} stocks · equal weight · {r['cash']:,.0f} JPY · {r['fee']}% one-way fee.\nData: {'downloaded (historical visibility unverified)' if r['template']=='market' else 'fictional demo'}. Review, then start backtest."))

    def run_guided(self):
        if self.jobs.busy or not self.guide_recipe: return False
        if self.guide_recipe!=self.recipe(): self._guide_changed(); return False
        self.mode.setCurrentIndex(self.mode.findData("backtest"))
        if self.guide_recipe["template"]=="market":
            self.invalidate_preflight()
            self.jobs.start({"action":"price_research","mode":"backtest","market_manifest":str(self.market_manifest),"recipe":self.guide_recipe})
            self._update_actions(); return True
        self.auto_history=True
        result=self.start_action("preflight")
        if not result: self.auto_history=False
        return result

    def _job_finished(self,job):
        if job["action"]=="guided_demo" and job["status"]=="COMPLETED":
            root=Path(job["result"]["result"]["demo_dir"])
            self.load_catalog(root); self.load_document(root/"backtest.json",choice="discard")
            self.guide_recipe=self.pending_recipe; self._show_recipe()
            self._save_recipe(self.guide_recipe,root/"backtest.json")
            self._refresh_jobs(); self._update_actions(); self.localize(); return
        super()._job_finished(job)
        if job["action"]=="demo" and job["status"]=="COMPLETED":
            self.template.setCurrentIndex(0)
            self._guide_changed(); self.nav.setCurrentRow(1)
        if job["action"]=="preflight" and self.auto_history:
            self.auto_history=False
            if job["status"]=="COMPLETED" and self.preflight_result and self.preflight_result.get("ok"):
                QTimer.singleShot(0,lambda:self.start_action("history"))
            else: self.data_advanced.setChecked(True); self.nav.setCurrentRow(2)
        self._update_actions(); self.localize()

    def show_report(self,report):
        super().show_report(report)
        if report.get("model")=="daily_bar_next_open_research_v1":
            self.trades_table.set_rows(report.get("trades",[]))
            self.trades_table.parentWidget().parentWidget().setCurrentIndex(1)
        self._localize_report()

    def _localize_report(self):
        if not self.report or not self.product_ready: return
        market=self.report.get("model")=="daily_bar_next_open_research_v1"
        if market:
            self.assumptions.setText(self.text("价格研究：前日信号、次日开盘成交、连续份额；未模拟整手/滑点/分红，严格 PIT 未认证。","価格研究：前日シグナル・翌日始値・連続数量。単元株/スリッページ/配当なし。厳密PIT未認証。","Price research: prior-close signal, next-open execution, continuous units; no board lots, slippage or dividends. Strict PIT unverified."))
            n=len(self.report.get("trades",[])); fees=self.report.get("fees",0)
            self.result_summary.setText(self.text(f"{n} 笔模拟交易 · 费用 {fees:,.2f} JPY · 无基准",f"{n} 件の模擬取引 · 手数料 {fees:,.2f} JPY · ベンチマークなし",f"{n} simulated trades · fees {fees:,.2f} JPY · no benchmark"))
            self.pages[3].itemAt(1).widget().setText(self.text("价格研究结果：数据与参数快照随运行保存。","価格研究結果：データと設定のスナップショットを保存します。","Price research results: data and settings are snapshotted with the run."))
            if self.nav.currentRow()==3:
                self.strategy_badge.setText(self.text("策略：","戦略：","Strategy: ")+self.report.get("recipe",{}).get("name",""))
                self.account_badge.setText(self.text("价格研究 · 独立模拟资金","価格研究 · 独立模擬資金","Price research · isolated simulated capital"))
                self.cutoff_badge.setText(self.text("研究结束：","研究終了：","Research end: ")+str(self.report.get("nav",[{}])[-1].get("at","")))
        elif self.report.get("model")=="daily_bar_open_with_previous_close_sizing_v2":
            self.pages[3].itemAt(1).widget().setText(self.text("本地真实数据：当日收盘后决策，下一交易日开盘模拟成交。","ローカル実データ：当日引け後に判断し、翌取引日始値で模擬約定。","Local historical data: post-close decision, simulated execution at the next session open."))
            self.assumptions.setText(self.text("研究范围以输入配置为准；已有日期/披露时刻，无额外D-1滞后；历史版本与交易单位待审计。","入力設定に従う研究。既存の日付・開示時刻を使用し、追加のD-1遅延なし。履歴版と売買単位は未監査。","Uses configured dates and disclosure timestamps, with no extra D-1 lag. Historical vintages and trading units remain unaudited."))
            n=len(self.report.get("decisions",[])); fills=len(self.report.get("journal",{}).get("fills",[]))
            self.result_summary.setText(self.text(f"{n} 次决策 · {fills} 笔模拟成交 · 本地真实数据",f"{n} 回の判断 · {fills} 件の模擬約定 · ローカル実データ",f"{n} decisions · {fills} simulated fills · local historical data"))
        else:
            self.pages[3].itemAt(1).widget().setText(tr("选择策略 → 数据预检 → 固定报价模拟 → 解释结果。所有运行保留配置快照。",self.language))
            self.assumptions.setText(tr("模型：fictional_fixed_quote_matching_v1；费用取 run.fees。基准未提供时不绘制；该结果不代表真实成交。",self.language))
            n=len(self.report.get("decisions",[]))
            self.result_summary.setText(self.text(f"{n} 次决策 · 虚构报价模拟 · 详见交易与诊断表",f"{n} 回の判断 · 架空価格の模擬約定 · 取引と診断表を参照",f"{n} decisions · fictional quote simulation · see trades and diagnostics"))

    def _market_ready(self,path):
        self.market_manifest=Path(path); self.settings.setValue("market_manifest",str(path))
        if hasattr(self,"market_status"):
            self.market_status.show()
            self.market_status.setText(self.text("下载清单已选择，可创建价格研究策略。","取得清単を選択しました。価格研究戦略を作成できます。","Download manifest selected. Create a price research strategy."))
        self._guide_changed()

    def pick_market(self):
        path,_=QFileDialog.getOpenFileName(self,self.text("选择已完成的下载清单","完了した取得清単を選択","Select completed download manifest"),str(self.workspace),"JSON (*.json)")
        if path:
            try:
                from .data_connection import load_bars
                load_bars(path); self._market_ready(path)
            except Exception as exc: self.market_status.show(); self.market_status.setText(str(exc))

    def toggle_advanced(self):
        visible=not self.advanced_editor.isVisible(); self.advanced_editor.setVisible(visible)
        self.advanced_toggle.setText("隐藏高级配置" if visible else "显示高级配置"); self.localize()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"editor_split"):
            self.editor_split.setOrientation(Qt.Orientation.Vertical if self.width()<1100 else Qt.Orientation.Horizontal)
            self.catalog.setMaximumHeight(140 if self.width()<1100 else 16777215)

    def _update_actions(self):
        super()._update_actions()
        if hasattr(self,"guide_box"):
            self.guide_box.setEnabled(not self.jobs.busy)
            self.guided_run.setEnabled(not self.jobs.busy and bool(self.guide_recipe))
            if self.guide_recipe: self.history_button.setEnabled(not self.jobs.busy)

    def load_document(self,*args,**kwargs):
        result=super().load_document(*args,**kwargs)
        if result and self.product_ready:
            self.guide_recipe=None
            self.strategy_badge.setText(self.text("当前策略：","現在の戦略：","Current strategy: ")+str(self.document.data.get("metadata",{}).get("display_name",self.document.data.get("id",""))))
            self.strategy_badge.setToolTip(self.strategy_badge.text()); self.localize()
        return result

    def _field_changed(self,*args):
        super()._field_changed(*args)
        if self.product_ready: self._guide_changed()

    def _json_changed(self):
        super()._json_changed()
        if self.product_ready: self._guide_changed()

    def set_language(self,language):
        self.language=language; self.settings.setValue("language",language)
        self.translator.language=language; self.connection.set_language(language)
        self.setWindowTitle("KabuForge · "+tr("日本股票策略研究工作台",language))
        if self.help_dialog: self.help_dialog.set_language(language)
        self._show_recipe(); self.localize()

    def localize(self):
        if not self.product_ready: return
        self.translator.language=self.language; self.translator.apply(self)
        self.nav_chart.language=self.language; self.drawdown_chart.language=self.language
        self.nav_chart.update(); self.drawdown_chart.update()
        for table in self.tables:
            for i,key in enumerate(table.columns): table.model.setHeaderData(i,Qt.Orientation.Horizontal,tr(key,self.language))
            for row in range(table.model.rowCount()):
                for col,key in enumerate(table.columns):
                    raw=table.rows[row].get(key,"")
                    if isinstance(raw,str): table.model.item(row,col).setText(tr(raw,self.language))
        self._localize_report()
        if self.jobs.jobs:
            job=self.jobs.jobs[-1]; status=job["status"]
            state={"COMPLETED":self.text("已完成","完了","Completed"),"FAILED":self.text("失败，详见运行记录","失敗。実行履歴を確認","Failed; see Run history"),"CANCELED":self.text("已取消","中止","Cancelled")}.get(status,self.text("运行中","実行中","Running"))
            self.statusBar().showMessage(state)
        if self.preflight_result:
            self.preflight_status.setText(self.text("预检通过","検証済み","Checks passed") if self.preflight_result.get("ok") else self.text("预检未通过，请查看诊断。","検証失敗。診断を確認してください。","Checks failed. See diagnostics."))
            self.strategy_badge.setText(self.text("策略：","戦略：","Strategy: ")+str(self.guide_recipe["name"] if self.guide_recipe else self.preflight_result.get("strategy_id","")))
            self.account_badge.setText(self.text("模拟账户：","模擬口座：","Simulated account: ")+str(self.preflight_result.get("account_id","")))
            self.cutoff_badge.setText(self.text("数据截止：","データ基準：","Data cutoff: ")+str(self.preflight_result.get("cutoff","")))
        if hasattr(self,"journal_value"): self._localize_journal()

    def show_journal(self,value):
        self.journal_value=value; super().show_journal(value)
        if self.product_ready: self._localize_journal()

    def _localize_journal(self):
        value=self.journal_value
        accounts=[f"{row.get('account_id','—')} · {float(row.get('equity',0)):,.2f} JPY" for row in value.get("accounts",[])]
        status=self.text("需对账；执行已阻断","照合が必要です。実行を停止","Reconciliation required; execution blocked") if value.get("blockers") else self.text("只读查询完成；不授权真实下单","読取専用照会完了。実発注は無効","Read-only query complete; live orders disabled")
        self.paper_summary.setText("\n".join(accounts)+"\n"+status)

    def show_help(self):
        if self.help_dialog is None: self.help_dialog=HelpDialog(getattr(self,"language","zh_CN"),self)
        self.help_dialog.show(); self.help_dialog.raise_(); self.help_dialog.activateWindow()

    def closeEvent(self,event):
        # Do not destroy a live download thread. User can explicitly cancel in Data center.
        if getattr(self.connection,"busy",False):
            self.nav.setCurrentRow(2)
            self.statusBar().showMessage(self.text("请等待数据任务完成，或先点击取消。","データ処理の完了を待つか中止してください。","Wait for the data task, or cancel it first."))
            event.ignore(); return
        super().closeEvent(event)
