"""User-facing KabuForge shell over the existing isolated execution workbench."""
from __future__ import annotations
import json,uuid,math
from pathlib import Path
from PySide6.QtCore import Qt,QSignalBlocker,QTimer
from PySide6.QtGui import QKeySequence,QShortcut,QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
    QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QGroupBox,QFileDialog,QMessageBox,QSizePolicy,QTabWidget)
from .workbench_qt import WorkbenchWindow
from .workbench_widgets import label
from .i18n import Translator,LANGUAGES,tr
from .guided_strategy import parse_sentence
from .help_viewer import HelpDialog
from .brand_theme import BRAND_DIR,branded_stylesheet,DARK

LANGUAGES_ORDER=("zh_CN","ja_JP","en_US")

class ProductWorkbench(WorkbenchWindow):
    def __init__(self,workspace,service=None):
        self.translator=Translator(); self.guide_recipe=None; self.market_manifest=None; self.auto_history=False
        self._market_source_mode=None; self._market_source_kind=None; self._market_status_state=None
        self._source_report_path=None
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
            if widget.text() in {"PRIVATE ENGINE","量化工作台","KABUFORGE","Research Workbench"}: widget.hide()
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
        if saved and Path(str(saved)).is_file(): self._market_ready(str(saved),{"origin":"local"})
        self.set_language(self.language)
        QShortcut(QKeySequence("Ctrl+Shift+D"),self,activated=self.open_data_diagnostics)
        QShortcut(QKeySequence("Ctrl+Return"),self,activated=self.preflight_button.click)
        QShortcut(QKeySequence("Ctrl+Shift+Return"),self,activated=self.history_button.click)
        QShortcut(QKeySequence("Ctrl+Shift+L"),self,activated=lambda:
                  self.language_picker.setCurrentIndex((self.language_picker.currentIndex()+1)%self.language_picker.count()))
        QShortcut(QKeySequence("Ctrl+Shift+O"),self,activated=self.open_report)

    def _build_research(self):
        super()._build_research()
        from .price_sensitivity_panel import PriceSensitivityPanel
        self.price_sensitivity_panel=PriceSensitivityPanel(self.workspace,"zh_CN",parent=self)
        self.price_sensitivity_panel.setProperty("ownTranslation",True)
        self.pages[3].addWidget(self.price_sensitivity_panel)

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
        self.template=QComboBox(); self.template.addItem("价格动量（选择本地行情）","market"); self.template.addItem("质量与趋势（虚构工程演示）","synthetic")
        self.signal_template=QComboBox(); self.signal_template.addItem("价格动量排序","price_momentum"); self.signal_template.addItem("MA 均线交叉（前收信号 / 次开盘）","sma_crossover")
        self.signal_provider=QComboBox(); self.signal_provider.addItem("Native 滚动平均","native"); self.signal_provider.addItem("TA-Lib SMA","talib")
        from .integrations import inspect_integrations
        self._talib_research_available=next((s.package_discoverable for s in inspect_integrations() if s.spec.id=="talib"),False)
        if not self._talib_research_available:
            self.signal_provider.model().item(1).setEnabled(False)
            self.signal_provider.setToolTip(self.text("TA-Lib 未发现；可继续使用 Native。","TA-Lib が見つかりません。Native は使用できます。","TA-Lib not discovered; Native remains available."))
        self.fast_period=QSpinBox(); self.fast_period.setRange(2,250); self.fast_period.setValue(20)
        self.slow_period=QSpinBox(); self.slow_period.setRange(3,500); self.slow_period.setValue(60)
        self.holding_count=QSpinBox(); self.holding_count.setRange(1,5); self.holding_count.setValue(5)
        self.frequency=QComboBox()
        for title,key in (("每月","monthly"),("每周","weekly"),("每日","daily")): self.frequency.addItem(title,key)
        self.weighting=QComboBox(); self.weighting.addItem("等权","equal_weight")
        self.cash=QDoubleSpinBox(); self.cash.setRange(10000,1e10); self.cash.setDecimals(0); self.cash.setSingleStep(100000); self.cash.setValue(2000000)
        self.fee=QDoubleSpinBox(); self.fee.setRange(0,5); self.fee.setDecimals(3); self.fee.setValue(.1)
        self.quality=QSpinBox(); self.quality.setRange(0,100); self.quality.setValue(50)
        self.lookback=QSpinBox(); self.lookback.setRange(2,500); self.lookback.setValue(20)
        self._momentum_controls=(self.holding_count.value(),"monthly"); self._crossover_active=False
        for title,widget in (("策略名称",self.strategy_name),("策略模板",self.template),("持仓数量",self.holding_count),
            ("信号模板",self.signal_template),("信号计算",self.signal_provider),("快线周期",self.fast_period),("慢线周期",self.slow_period),
            ("调仓频率",self.frequency),("权重方式",self.weighting),("初始资金（JPY）",self.cash),
            ("费用（单边，%）",self.fee),("质量占比（%）",self.quality),("动量观察期（交易日）",self.lookback)):
            form.addRow(title,widget)
        self.lookback.setEnabled(False); self.strategy_form=form
        self.sentence=QLineEdit(); self.sentence.setPlaceholderText("每月选5只股票，等权")
        self.parse_button=self._button("解析到表单",self.parse_input)
        sentence_box=QWidget(); row=QHBoxLayout(sentence_box); row.setContentsMargins(0,0,0,0); row.addWidget(self.sentence,1); row.addWidget(self.parse_button)
        form.addRow("用一句话辅助填写",sentence_box)
        form.addRow(label("本地解析只支持数量、频率、等权。其余条件请用表单设置；不会自动运行。","subtleText"))
        self.ma_semantics_note=label("MA 交叉每日检查全部选择的证券；仓位取决于信号与可用资金。","subtleText")
        self.ma_semantics_note.setProperty("ownTranslation",True); self.ma_semantics_note.hide(); form.addRow(self.ma_semantics_note)
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
        self.signal_template.currentIndexChanged.connect(self._template_changed)
        self.signal_provider.currentIndexChanged.connect(self._guide_changed)
        for widget in (self.strategy_name,self.sentence): widget.textChanged.connect(self._guide_changed)
        for widget in (self.holding_count,self.cash,self.fee,self.quality,self.lookback,self.fast_period,self.slow_period): widget.valueChanged.connect(self._guide_changed)
        self.frequency.currentIndexChanged.connect(self._guide_changed)
        page.addStretch()

    def _build_data(self):
        from .local_cache_panel import LocalCachePanel
        from .factor_cache_panel import FactorCachePanel
        from .indicator_panel import IndicatorResearchPanel
        from .factor_research_panel import FactorResearchPanel
        from .research_studio_panel import ResearchStudioPanel
        from .integrations_panel import IntegrationsPanel
        page=self.pages[2]
        self.integrations_panel=IntegrationsPanel(language="zh_CN",parent=self)
        self.integrations_panel.setProperty("ownTranslation",True); page.addWidget(self.integrations_panel)
        # The connection panel reads an existing Windows credential reference in
        # its constructor. Create it only after the user explicitly opens J-Quants.
        self.connection=None
        self.connection_host=QWidget(); self.connection_layout=QVBoxLayout(self.connection_host)
        self.connection_button=self._button("打开 J-Quants 连接与下载",self._open_jquants_connection)
        self.connection_button.setProperty("ownTranslation",True)
        self.connection_layout.addWidget(self.connection_button); page.addWidget(self.connection_host)
        self.local_cache_panel=LocalCachePanel(self.workspace,language="zh_CN",parent=self)
        self.local_cache_panel.setProperty("ownTranslation",True)
        self.local_cache_panel.input_ready.connect(self._market_ready)
        self.local_cache_panel.input_invalidated.connect(self._market_invalidated); page.addWidget(self.local_cache_panel)
        self.factor_cache_panel=FactorCachePanel(self.workspace,language="zh_CN",parent=self)
        self.factor_cache_panel.setProperty("ownTranslation",True)
        self.factor_cache_panel.enabled_changed.connect(self.invalidate_preflight); page.addWidget(self.factor_cache_panel)
        self.market_pick=self._button("选择已下载的数据",self.pick_market); self.market_pick.setProperty("ownTranslation",True); page.addWidget(self.market_pick)
        self.market_status=label("","detailText"); self.market_status.setProperty("ownTranslation",True); page.addWidget(self.market_status)
        self.indicator_panel=IndicatorResearchPanel(self.workspace,language="zh_CN",parent=self); self.indicator_panel.setProperty("ownTranslation",True); page.addWidget(self.indicator_panel)
        self.tables.append(self.indicator_panel.table)
        self.factor_research_panel=FactorResearchPanel(self.workspace,language="zh_CN",parent=self); self.factor_research_panel.setProperty("ownTranslation",True); page.addWidget(self.factor_research_panel)
        self.research_studio_panel=ResearchStudioPanel(self.workspace,self.factor_research_panel,language="zh_CN",parent=self)
        self.research_studio_panel.setProperty("ownTranslation",True)
        self.research_studio_panel.strategy_report_ready.connect(self.show_report); page.addWidget(self.research_studio_panel)
        self.data_advanced=QGroupBox("高级配置与诊断"); self.data_advanced.setCheckable(True); self.data_advanced.setChecked(False)
        box=QVBoxLayout(self.data_advanced); content=QWidget(); inner=QVBoxLayout(content)
        original=self.pages[2]; self.pages[2]=inner; super()._build_data(); self.pages[2]=original
        box.addWidget(content); content.hide(); self.data_advanced.toggled.connect(content.setVisible); page.addWidget(self.data_advanced)
        page.addStretch(1)
        self.market_status.hide()

    def _open_jquants_connection(self):
        if self.connection is not None:
            self.connection.show(); return self.connection
        from .data_connection_qt import DataConnectionPanel
        self.connection=DataConnectionPanel(self.workspace,language=self.language,parent=self.connection_host)
        self.connection.setProperty("ownTranslation",True)
        self.connection.downloaded.connect(lambda path:self._market_ready(
            path,{"origin":"download","source":{"kind":"jquants_api_download"}}))
        self.connection_layout.addWidget(self.connection); self.connection_button.hide()
        self.connection.set_language(self.language)
        return self.connection

    def _build_paper(self):
        from .historical_paper_panel import HistoricalPaperPanel
        page=self.pages[4]
        self.historical_paper_panel=HistoricalPaperPanel(self.workspace,language="zh_CN",parent=self)
        self.historical_paper_panel.setProperty("ownTranslation",True)
        self.paper_tabs=QTabWidget(); self.paper_tabs.addTab(self.historical_paper_panel,"本地历史研究回放")
        original=self.pages[4]; legacy=QVBoxLayout(); self.pages[4]=legacy
        super()._build_paper(); self.pages[4]=original
        self.legacy_paper_box=QGroupBox("旧 Paper / 状态诊断"); self.legacy_paper_box.setCheckable(True); self.legacy_paper_box.setChecked(False)
        container=QWidget(); container.setLayout(legacy); container.hide(); layout=QVBoxLayout(self.legacy_paper_box); layout.addWidget(container)
        self.legacy_paper_box.toggled.connect(container.setVisible); self.paper_tabs.addTab(self.legacy_paper_box,"旧版诊断")
        page.addWidget(self.paper_tabs)

    def _build_brokers(self):
        from .broker_research_panel import BrokerResearchPanel
        page=self.pages[5]
        self.broker_research_panel=BrokerResearchPanel(self.workspace,language="zh_CN",parent=self)
        self.broker_research_panel.setProperty("ownTranslation",True)
        self.broker_tabs=QTabWidget(); self.broker_tabs.addTab(self.broker_research_panel,"离线订单映射预览")
        original=self.pages[5]; legacy=QVBoxLayout(); self.pages[5]=legacy
        super()._build_brokers(); self.pages[5]=original
        self.legacy_broker_box=QGroupBox("旧券商能力诊断"); self.legacy_broker_box.setCheckable(True); self.legacy_broker_box.setChecked(False)
        container=QWidget(); container.setLayout(legacy); container.hide(); layout=QVBoxLayout(self.legacy_broker_box); layout.addWidget(container)
        self.legacy_broker_box.toggled.connect(container.setVisible); self.broker_tabs.addTab(self.legacy_broker_box,"旧版能力表")
        page.addWidget(self.broker_tabs)

    def _template_changed(self,*_):
        market=self.template.currentData()=="market"
        crossover=market and self.signal_template.currentData()=="sma_crossover"
        if crossover and not self._crossover_active:
            self._momentum_controls=(self.holding_count.value(),self.frequency.currentData())
            count_blocker=QSignalBlocker(self.holding_count); frequency_blocker=QSignalBlocker(self.frequency)
            self.holding_count.setValue(1); self.frequency.setCurrentIndex(self.frequency.findData("daily"))
            del count_blocker,frequency_blocker
        elif not crossover and self._crossover_active:
            count_blocker=QSignalBlocker(self.holding_count); frequency_blocker=QSignalBlocker(self.frequency)
            self.holding_count.setValue(self._momentum_controls[0])
            self.frequency.setCurrentIndex(self.frequency.findData(self._momentum_controls[1]))
            del count_blocker,frequency_blocker
        self._crossover_active=crossover
        self.holding_count.setMaximum(100 if market else 5)
        self.holding_count.setEnabled(not crossover); self.frequency.setEnabled(not crossover)
        self.signal_template.setEnabled(market); self.signal_provider.setEnabled(crossover)
        self.fast_period.setEnabled(crossover); self.slow_period.setEnabled(crossover)
        self.quality.setEnabled(not market); self.lookback.setEnabled(market and not crossover)
        self.ma_semantics_note.setVisible(crossover); self._localize_ma_note(); self._guide_changed()

    def _localize_ma_note(self):
        self.ma_semantics_note.setText(self.text(
            "MA 交叉每日检查所有选择证券；仓位由实际信号与可用资金决定，持仓数量和调仓频率不参与。",
            "MAクロスは選択銘柄を毎日確認します。保有はシグナルと利用可能資金で決まり、銘柄数・頻度は適用されません。",
            "MA crossover checks all selected symbols daily. Holdings follow signals and available cash; holding count and rebalance frequency do not apply."))

    def experience_demo(self):
        if self.jobs.busy: return False
        self.template.setCurrentIndex(self.template.findData("synthetic")); self.holding_count.setValue(5)
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
        recipe={"name":self.strategy_name.text().strip(),"template":self.template.currentData(),"count":self.holding_count.value(),
                "frequency":self.frequency.currentData(),"cash":self.cash.value(),"fee":self.fee.value(),
                "quality":self.quality.value(),"lookback":self.lookback.value(),"weighting":"equal_weight"}
        if recipe["template"]=="market":
            recipe.update(signal_template=self.signal_template.currentData(),signal_provider=self.signal_provider.currentData(),
                          fast_period=self.fast_period.value(),slow_period=self.slow_period.value())
        return recipe

    def _request(self,action):
        request=super()._request(action)
        target=request.get("target_action",action)
        market=bool(self.guide_recipe and self.guide_recipe.get("template")=="market")
        eligible=request.get("mode")=="backtest" and target=="history" and not market
        request["factor_cache"]=self.factor_cache_panel.selection(
            enabled=self.factor_cache_panel.is_enabled() and eligible)
        return request

    def invalidate_preflight(self,*args):
        super().invalidate_preflight(*args)
        panel=getattr(self,"factor_cache_panel",None)
        if panel is not None: panel.clear_summary()

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
        if recipe["template"]=="market" and recipe.get("signal_template")=="sma_crossover":
            if recipe["fast_period"]>=recipe["slow_period"]:
                self.guide_summary.setText(self.text("快线周期必须小于慢线周期。","短期期間は長期期間より小さくしてください。","Fast period must be shorter than slow period.")); return False
            if recipe.get("signal_provider")=="talib" and not self._talib_research_available:
                self.guide_summary.setText(self.text("TA-Lib 当前不可用，请使用 Native。","TA-Lib は利用できません。Native を選択してください。","TA-Lib is unavailable; choose Native.")); return False
        if not recipe["name"]:
            self.guide_summary.setText(self.text("请输入策略名称。","戦略名を入力してください。","Enter a strategy name.")); return False
        if not self._confirm_unsaved(): return False
        if recipe["template"]=="market":
            if not self.market_manifest or not self.market_manifest.is_file():
                self.guide_summary.setText(self.text("请先在本地行情面板选择并冻结数据，或明确选择已完成的 J-Quants 下载清单。","ローカルデータを選択・固定するか、完了済みの J-Quants マニフェストを選択してください。","Select and freeze local bars, or explicitly choose a completed J-Quants manifest first.")); return False
            self._save_recipe(recipe)
            self.guide_recipe=recipe; self._show_recipe(); self._update_actions(); return True
        self.jobs.start({"action":"guided_demo","recipe":recipe,"mode":"backtest"}); self.pending_recipe=recipe; self._update_actions(); return True

    def _show_recipe(self):
        if not self.guide_recipe: return
        r=self.guide_recipe; freq=tr({"monthly":"每月","weekly":"每周","daily":"每日"}[r["frequency"]],self.language)
        crossover=r.get("signal_template")=="sma_crossover"
        strategy_text=(self.text(f" · MA交叉 SMA{r.get('fast_period')}/{r.get('slow_period')}（{r.get('signal_provider','native')}）· 前收定量、次开盘执行",
            f" · MAクロス SMA{r.get('fast_period')}/{r.get('slow_period')}（{r.get('signal_provider','native')}）· 前日終値で数量固定、翌日始値で執行",
            f" · MA crossover SMA{r.get('fast_period')}/{r.get('slow_period')} ({r.get('signal_provider','native')}) · prior-close sizing, next-open execution") if crossover else "")
        if r["template"]=="market":
            kind=self._market_source_kind or "local market data"
            source_label=self.text(f"本地/下载行情（{kind}；历史可见性未认证）",f"ローカル/取得データ（{kind}；過去の可視性は未認証）",f"Local/downloaded bars ({kind}; historical visibility unverified)")
        else:
            source_label=self.text("虚构工程演示数据", "架空の工程デモデータ", "Fictional engineering demo data")
        self.guide_summary.setText(self.text(
            f"已创建：{r['name']} · {freq} · {r['count']} 只 · 等权 · {r['cash']:,.0f} JPY · 单边费用 {r['fee']}%{strategy_text}。\n数据：{source_label}。确认后点击开始回测。",
            f"作成済み：{r['name']} · {freq} · {r['count']} 銘柄 · 均等配分 · {r['cash']:,.0f} JPY · 片道 {r['fee']}%{strategy_text}。\nデータ：{source_label}。確認後にバックテストを開始してください。",
            f"Created: {r['name']} · {freq} · {r['count']} stocks · equal weight · {r['cash']:,.0f} JPY · {r['fee']}% one-way fee{strategy_text}.\nData: {source_label}. Review, then start backtest."))

    def run_guided(self):
        if self.jobs.busy or not self.guide_recipe: return False
        if self.guide_recipe!=self.recipe(): self._guide_changed(); return False
        self.mode.setCurrentIndex(self.mode.findData("backtest"))
        if self.guide_recipe["template"]=="market":
            if not self.market_manifest: return False
            request=self._request("preflight")
            request.update(target_action="price_research",market_manifest=str(self.market_manifest),recipe=self.guide_recipe)
            self.invalidate_preflight(); self.auto_history=True; self.pending_market_research=True
            try:
                self.jobs.start(request); self._update_actions(); return True
            except Exception as exc:
                self.auto_history=False; self.pending_market_research=False
                self.statusBar().showMessage(str(exc)); return False
        self.auto_history=True
        self.pending_market_research=False
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
        if job["action"]=="history" and hasattr(self,"factor_cache_panel"):
            result=((job.get("result") or {}).get("result") or {})
            if job.get("status")=="COMPLETED" and isinstance(result.get("factor_cache"),dict):
                self.factor_cache_panel.show_summary(result["factor_cache"])
            elif job.get("status")=="FAILED":
                receipt=Path(job.get("output_dir",""))/job.get("job_id","")/"factor_cache_failure.json"
                if receipt.is_file(): self.factor_cache_panel.show_failure(receipt)
        if job["action"]=="demo" and job["status"]=="COMPLETED":
            self.template.setCurrentIndex(0)
            self._guide_changed(); self.nav.setCurrentRow(1)
        if job["action"]=="preflight" and self.auto_history:
            self.auto_history=False
            if job["status"]=="COMPLETED" and self.preflight_result and self.preflight_result.get("ok"):
                if getattr(self,"pending_market_research",False):
                    self.pending_market_research=False; QTimer.singleShot(0,self._start_price_research)
                else: QTimer.singleShot(0,lambda:self.start_action("history"))
            else:
                self.pending_market_research=False; self.data_advanced.setChecked(True); self.nav.setCurrentRow(2)
        self._update_actions(); self.localize()

    def _start_price_research(self):
        if not self.guide_recipe or not self.market_manifest or not self.preflight_result: return False
        request={"action":"price_research","mode":"backtest","market_manifest":str(self.market_manifest),
            "recipe":self.guide_recipe,"expected_fingerprint":self.preflight_result.get("fingerprint"),
            "regime_observer":{"mode":"off"}}
        try:
            self.jobs.start(request); self._update_actions(); return True
        except Exception as exc:
            self.statusBar().showMessage(str(exc)); return False

    def show_report(self,report,*,source_report_path=None):
        self._source_report_path=str(Path(source_report_path).resolve(strict=True)) if source_report_path else None
        super().show_report(report,source_report_path=source_report_path)
        if hasattr(self,"price_sensitivity_panel"):
            self.price_sensitivity_panel.set_source(self._source_report_path)
        if report.get("model")=="daily_bar_next_open_research_v1":
            self.trades_table.set_rows(report.get("trades",[]))
            self.trades_table.parentWidget().parentWidget().setCurrentIndex(1)
        self._localize_report()

    @staticmethod
    def _fee_display(value):
        if isinstance(value,bool) or not isinstance(value,(int,float)): return "—"
        try: amount=float(value)
        except (TypeError,ValueError,OverflowError): return "—"
        return f"{amount:,.2f}" if math.isfinite(amount) else "—"

    def _report_strategy_name(self,report,template):
        if template=="sma_crossover":
            return self.text("MA 均线交叉","MAクロス","MA crossover")
        if template in {"frozen_factor_feature_rows","frozen_model_predictions"}:
            return self.text("因子评分策略" if template=="frozen_factor_feature_rows" else "模型评分策略",
                "ファクタースコア戦略" if template=="frozen_factor_feature_rows" else "モデルスコア戦略",
                "Factor score strategy" if template=="frozen_factor_feature_rows" else "Model score strategy")
        recipe=report.get("strategy_recipe") or report.get("recipe") or {}
        if not isinstance(recipe,dict): recipe={}
        return (recipe.get("name") or report.get("strategy_name") or report.get("strategy_id")
                or self.text("研究报告","研究レポート","Research report"))

    def _localize_report(self):
        if not self.report: return
        market=self.report.get("model")=="daily_bar_next_open_research_v1"
        recipe=self.report.get("strategy_recipe") or self.report.get("recipe") or {}
        if not isinstance(recipe,dict): recipe={}
        template=self.report.get("strategy_template") or recipe.get("signal_template") or ""
        strategy_name=self._report_strategy_name(self.report,template)
        self.strategy_badge.setText(self.text("策略：","戦略：","Strategy: ")+str(strategy_name))
        self.strategy_badge.setToolTip(self.strategy_badge.text())
        nav_rows=self.report.get("nav") or []
        identity=self.report.get("input_identity") or {}
        date_range=identity.get("source_date_range") or identity.get("coverage") or {}
        cutoff=(nav_rows[-1].get("at") if nav_rows else None) or (date_range.get("end") if isinstance(date_range,dict) else None)
        self.cutoff_badge.setText(self.text("研究结束：","研究終了：","Research end: ")+str(cutoff or "—"))
        self.account_badge.setText(self.text("价格研究 · 独立模拟资金","価格研究 · 独立模擬資金","Price research · isolated simulated capital")
                                   if market else self.text("研究运行 · 非真实账户","研究実行 · 実口座ではありません","Research run · no live account"))
        if market:
            template=self.report.get("strategy_template") or recipe.get("signal_template")
            self.assumptions.setText(self.text("价格研究：前日信号、次日开盘成交、连续份额；未模拟整手/滑点/分红，严格 PIT 未认证。","価格研究：前日シグナル・翌日始値・連続数量。単元株/スリッページ/配当なし。厳密PIT未認証。","Price research: prior-close signal, next-open execution, continuous units; no board lots, slippage or dividends. Strict PIT unverified."))
            n=len(self.report.get("trades",[])); skipped=len(self.report.get("skipped_orders",[])); fees=self._fee_display(self.report.get("fees"))
            benchmark=self.report.get("benchmark_provenance",{}).get("benchmark")=="TOPIX"
            bm=self.text("TOPIX 价格指数（不含股息）","TOPIX価格指数（配当なし）","TOPIX price index (dividends excluded)") if benchmark else self.text("未载入TOPIX","TOPIX未読込","TOPIX not loaded")
            if template=="sma_crossover":
                self.assumptions.setText(self.text(f"MA交叉 SMA{self.report.get('strategy_parameters',{}).get('fast_period')}/{self.report.get('strategy_parameters',{}).get('slow_period')}：前收信号与定量、次日开盘执行；缺现金买单跳过，不按未来开盘价重定量。连续份额、价格估值；严格 PIT 未认证。",
                    f"MAクロス SMA{self.report.get('strategy_parameters',{}).get('fast_period')}/{self.report.get('strategy_parameters',{}).get('slow_period')}：前日終値でシグナル・数量を固定し、翌日始値で執行。資金不足の買いはスキップし、始値で再計算しません。厳密PIT未認証。",
                    f"MA crossover SMA{self.report.get('strategy_parameters',{}).get('fast_period')}/{self.report.get('strategy_parameters',{}).get('slow_period')}: prior-close signal and sizing, next-open execution; cash-short buys are skipped without resizing. Strict PIT unverified."))
            self.result_summary.setText(self.text(f"已成交订单 {n} · 跳过 {skipped} · 费用 {fees} JPY · {bm}。订单数不等于已平仓交易数。",
                f"約定注文 {n} · スキップ {skipped} · 手数料 {fees} JPY · {bm}。注文数は決済取引数ではありません。",
                f"Filled orders {n} · skipped {skipped} · fees {fees} JPY · {bm}. Orders are not closed trades."))
            self.pages[3].itemAt(1).widget().setText(self.text("价格研究结果：数据与参数快照随运行保存。","価格研究結果：データと設定のスナップショットを保存します。","Price research results: data and settings are snapshotted with the run."))
            self.account_badge.setText(self.text("价格研究 · 独立模拟资金","価格研究 · 独立模擬資金","Price research · isolated simulated capital"))
            self.cutoff_badge.setText(self.text("研究结束：","研究終了：","Research end: ")+str((self.report.get("nav") or [{}])[-1].get("at","")))
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

    def _market_ready(self,path,summary=None):
        try:
            from .price_research import _load_price_research_input
            _rows,identity=_load_price_research_input(path)
            source=(summary or {}).get("source") or identity.get("input_source",{}) or {}
            kind=source.get("kind") if isinstance(source,dict) else None
            document={}
            if not kind:
                try: document=json.loads(Path(path).read_text(encoding="utf-8"))
                except (OSError,ValueError,TypeError): document={}
                if document.get("kind")=="kabuforge_local_research_bars": kind=(document.get("source") or {}).get("kind","local frozen manifest")
                elif document.get("kind")=="jquants_equities_daily_bars": kind="jquants API download"
                else: kind=document.get("format",Path(path).suffix.lstrip(".")) or "local file"
            origin=(summary or {}).get("origin") or ("download" if kind=="jquants_api_download" else "local")
            self.market_manifest=Path(path).expanduser().resolve(strict=True)
            self._market_source_kind=str(kind); self._market_source_mode=origin
            self._market_status_state="ready"; self._market_status_error=""
            self.settings.setValue("market_manifest",str(self.market_manifest))
        except Exception as exc:
            self._market_status_state="error"; self._market_status_error=str(exc)
            self.market_manifest=None; self._market_source_mode=None; self._market_source_kind=None
            self._render_market_status(); self._guide_changed(); return False
        self.indicator_panel.set_manifest(self.market_manifest)
        self.factor_research_panel.set_manifest(self.market_manifest)
        self.research_studio_panel.set_manifest(self.market_manifest)
        same_manifest=self.historical_paper_panel.manifest_path==str(self.market_manifest)
        old_report=self.historical_paper_panel.report_path if same_manifest else None
        old_sha=self.historical_paper_panel.report_sha if same_manifest else None
        self.historical_paper_panel.set_inputs(self.market_manifest,old_report,old_sha)
        self._render_market_status(); self._guide_changed(); return True

    def _render_market_status(self):
        if not hasattr(self,"market_status"): return
        if self._market_status_state=="ready":
            kind=self._market_source_kind or "local source"
            text=(self.text(f"本地缓存已就绪（{kind}）；历史可见性未认证。","ローカルキャッシュを選択しました（{kind}）；過去の可視性は未認証です。","Local cache selected ({kind}); historical visibility is unverified.")
                  if self._market_source_mode=="local" else self.text(f"J-Quants 下载已就绪（{kind}）；历史可见性未认证。","J-Quants取得データを選択しました（{kind}）；過去の可視性は未認証です。","J-Quants download selected ({kind}); historical visibility is unverified."))
            self.market_status.setText(text); self.market_status.show()
        elif self._market_status_state=="error":
            self.market_status.setText(self.text("行情输入验证失败：","市場データ入力を検証できません：","Market input validation failed: ")+self._market_status_error); self.market_status.show()
        else:
            self.market_status.clear(); self.market_status.hide()

    def _market_invalidated(self):
        self.market_manifest=None; self._market_source_mode=None; self._market_source_kind=None; self._market_status_state=None
        self.settings.remove("market_manifest")
        self.indicator_panel.clear_manifest(); self.factor_research_panel.clear_manifest(); self.research_studio_panel.clear_manifest()
        self.historical_paper_panel.set_inputs(None,None,None)
        self._market_status_error=""
        self.price_sensitivity_panel.set_source(None)
        self._render_market_status(); self._guide_changed()

    def pick_market(self):
        path,_=QFileDialog.getOpenFileName(self,self.text("选择已冻结的本地行情或完成下载清单","固定済みローカルデータまたは取得マニフェストを選択","Select a frozen local manifest or completed download manifest"),str(self.workspace),"JSON (*.json)")
        if path:
            self._market_ready(path,{"origin":"local"})

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
        if hasattr(self,"factor_cache_panel"):
            self.factor_cache_panel.set_busy(self.jobs.busy)

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
        if language not in LANGUAGES: language="zh_CN"
        self.language=language; self.settings.setValue("language",language)
        self.translator.language=language
        for name in ("connection","local_cache_panel","factor_cache_panel","indicator_panel",
                     "factor_research_panel","research_studio_panel","historical_paper_panel",
                     "broker_research_panel","integrations_panel","price_sensitivity_panel"):
            panel=getattr(self,name,None)
            setter=getattr(panel,"set_language",None)
            if callable(setter): setter(language)
        self.setWindowTitle("KabuForge · "+tr("日本股票策略研究工作台",language))
        if hasattr(self,"language_picker") and self.language_picker.currentData()!=language:
            blocker=QSignalBlocker(self.language_picker)
            self.language_picker.setCurrentIndex(self.language_picker.findData(language))
            del blocker
        if self.help_dialog: self.help_dialog.set_language(language)
        self._show_recipe(); self._localize_ma_note(); self._render_market_status(); self.localize()
        if hasattr(self,"guide_summary") and not self.guide_recipe:
            self.guide_summary.setText(self.text("设置已更改；请检查并创建策略。","設定を変更しました。確認して戦略を作成してください。","Settings changed. Review and create the strategy."))
        self._localize_editor_controls()
        if hasattr(self,"market_pick"):
            self.market_pick.setText(self.text("选择已冻结的行情输入","固定済み市場データを選択","Choose frozen market input"))
        if hasattr(self,"template"):
            self._localize_editor_controls()
        if hasattr(self,"connection_button"):
            self.connection_button.setText(self.text("打开 J-Quants 连接与下载","J-Quants 接続とデータ取得を開く","Open J-Quants connection and download"))
        for tabs,labels in ((getattr(self,"paper_tabs",None),(
                self.text("本地历史研究回放","ローカル履歴リプレイ","Local historical replay"),
                self.text("旧版诊断","旧診断","Legacy diagnostics"))),
                (getattr(self,"broker_tabs",None),(
                self.text("离线订单映射预览","オフライン注文マッピング","Offline order mapping"),
                self.text("旧版能力表","旧機能一覧","Legacy capability table")))):
            if tabs:
                for index,title in enumerate(labels): tabs.setTabText(index,title)
        if hasattr(self,"dashboard_button"):
            self.set_dashboard_language(language)

    def _localize_editor_controls(self):
        if not hasattr(self,"strategy_form"): return
        fields={
            "策略名称":("策略名称","戦略名","Strategy name"),
            "策略模板":("策略模板","戦略テンプレート","Strategy template"),
            "持仓数量":("持仓数量","保有銘柄数","Holdings"),
            "信号模板":("信号模板","シグナル方式","Signal template"),
            "信号计算":("信号计算","シグナル計算","Signal calculation"),
            "快线周期":("快线周期","短期期間","Fast period"),
            "慢线周期":("慢线周期","長期期間","Slow period"),
            "调仓频率":("调仓频率","リバランス頻度","Rebalance frequency"),
            "权重方式":("权重方式","配分方法","Weighting"),
            "初始资金（JPY）":("初始资金（JPY）","初期資金（JPY）","Initial cash (JPY)"),
            "费用（单边，%）":("费用（单边，%）","手数料（片道、%）","Fee (one way, %)"),
            "质量占比（%）":("质量占比（%）","品質比率（%）","Quality weight (%)"),
            "动量观察期（交易日）":("动量观察期（交易日）","モメンタム期間（取引日）","Momentum lookback (sessions)"),
            "用一句话辅助填写":("用一句话辅助填写","文章で入力を補助","Fill from a sentence"),
        }
        for row in range(self.strategy_form.rowCount()):
            item=self.strategy_form.itemAt(row,QFormLayout.ItemRole.LabelRole)
            widget=item.widget() if item else None
            if not isinstance(widget,QLabel): continue
            labels=fields.get(widget.text())
            if labels: widget.setText(labels[LANGUAGES_ORDER.index(self.language)])
        translations={
            "template":(("价格动量（选择本地行情）","価格モメンタム（ローカルデータを選択）","Price momentum (select local data)"),
                        ("质量与趋势（虚构工程演示）","品質とトレンド（架空の技術デモ）","Quality and trend (synthetic engineering demo)")),
            "signal_template":(("价格动量排序","価格モメンタム順位","Price momentum ranking"),
                               ("MA 均线交叉（前收信号 / 次开盘）","MAクロス（前日終値シグナル／翌日始値執行）","MA crossover (prior-close signal / next-open execution)")),
            "signal_provider":(("Native 滚动平均","Native 移動平均","Native rolling average"),("TA-Lib SMA","TA-Lib SMA","TA-Lib SMA")),
            "frequency":(("每月","毎月","Monthly"),("每周","毎週","Weekly"),("每日","毎日","Daily")),
            "weighting":(("等权","均等配分","Equal weight"),),
        }
        for name,rows in translations.items():
            combo=getattr(self,name,None)
            if combo is None: continue
            blocker=QSignalBlocker(combo)
            for index,locales in enumerate(rows):
                if index<combo.count(): combo.setItemText(index,locales[LANGUAGES_ORDER.index(self.language)])
            del blocker

    def localize(self):
        if not self.product_ready and not self.report: return
        self.translator.language=self.language; self.translator.apply(self)
        if hasattr(self,"nav"):
            nav_titles={"zh_CN":["首页","我的策略","数据中心","回测结果","纸上交易","券商连接","运行记录"],
                        "ja_JP":["ホーム","マイ戦略","データセンター","バックテスト結果","ペーパートレード","証券会社接続","実行履歴"],
                        "en_US":["Home","My strategies","Data center","Backtest results","Paper trading","Broker connections","Run history"]}[self.language]
            for index,title in enumerate(nav_titles):
                self.nav.item(index).setText(title); self.pages[index].itemAt(0).widget().setText(title)
        self.nav_chart.language=self.language; self.drawdown_chart.language=self.language
        self.nav_chart.update(); self.drawdown_chart.update()
        for table in self.tables:
            for i,key in enumerate(table.columns): table.model.setHeaderData(i,Qt.Orientation.Horizontal,tr(key,self.language))
            for row in range(table.model.rowCount()):
                for col,key in enumerate(table.columns):
                    raw=table.rows[row].get(key,"")
                    if isinstance(raw,str): table.model.item(row,col).setText(tr(raw,self.language))
        self._localize_report()
        self._render_market_status()
        self._localize_ma_note()
        for name in ("indicator_panel","factor_research_panel","research_studio_panel",
                     "historical_paper_panel","broker_research_panel","price_sensitivity_panel",
                     "factor_cache_panel","integrations_panel","local_cache_panel"):
            panel=getattr(self,name,None)
            setter=getattr(panel,"set_language",None)
            if callable(setter) and getattr(panel,"language",None)!=self.language:
                setter(self.language)
        self._localize_editor_controls()
        if self.jobs.jobs:
            job=self.jobs.jobs[-1]; status=job["status"]
            state={"COMPLETED":self.text("已完成","完了","Completed"),"FAILED":self.text("失败，详见运行记录","失敗。実行履歴を確認","Failed; see Run history"),"CANCELED":self.text("已取消","中止","Cancelled")}.get(status,self.text("运行中","実行中","Running"))
            self.statusBar().showMessage(state)
        if self.preflight_result and not self.report:
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
        # Child workers belong to their panels. Keep the parent alive until all finish.
        busy=[]
        for name in ("connection","local_cache_panel","factor_research_panel","research_studio_panel",
                     "historical_paper_panel","broker_research_panel","price_sensitivity_panel","indicator_panel"):
            panel=getattr(self,name,None)
            if panel is None: continue
            value=getattr(panel,"busy",False)
            if callable(value): value=value()
            if name=="local_cache_panel": value=value or getattr(panel,"_task",None) is not None
            check=getattr(panel,"_is_busy",None)
            if callable(check): value=bool(value or check())
            if value: busy.append(name)
        if busy:
            page=2 if any(n in busy for n in ("connection","local_cache_panel","factor_research_panel","indicator_panel")) else (4 if "historical_paper_panel" in busy else (5 if "broker_research_panel" in busy else 3))
            self.nav.setCurrentRow(page)
            self.statusBar().showMessage(self.text("请等待本工作台的后台任务完成后再关闭。","バックグラウンド処理の完了後に閉じてください。","Wait for this workbench's background tasks to finish before closing."))
            event.ignore(); return
        super().closeEvent(event)
