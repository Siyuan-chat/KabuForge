"""Asynchronous, explicit-manifest factor diagnostics for ProductWorkbench."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)
from PySide6.QtWebEngineWidgets import QWebEngineView

from .factor_research import DEFAULT_RECIPE
from .workbench_widgets import label


_LANG = {
    "zh_CN": {
        "title": "因子诊断 · RESEARCH-ONLY", "intro": "仅使用明确选择的冻结本地行情。显示 IC、分位、覆盖与换手诊断；不代表策略净值或投资结论。",
        "manifest": "冻结行情清单", "pick": "选择清单…", "factor": "价格动量特征（窗口 / 方向 / 权重）", "window_fast": "短窗口", "window_slow": "长窗口", "direction": "方向", "positive": "正向", "negative": "反向",
        "weight": "权重", "normalization": "横截面标准化", "rank": "秩标准化", "zscore": "Z-score",
        "horizon": "未来标签期限（交易日）", "minimum": "最小横截面数", "quantiles": "分位组数",
        "run": "运行因子诊断", "no_manifest": "请先选择数据中心中的冻结 manifest。不会自动扫描目录或下载数据。",
        "selected": "已选择显式本地输入。历史可见时间未验证；报告为 RESEARCH-ONLY。",
        "running": "正在后台计算特征和独立标签面板…", "building": "计算完成，正在生成三语本地图表…",
        "loading": "图表文件已生成，正在本地加载…", "ready": "六类图表已加载。报告不包含策略订单或NAV。",
        "failed": "因子研究失败：", "chart_failed": "计算已完成，但图表不可用：", "recipe_error": "配置无效：",
        "summary": "信号日期：{start} 至 {end} · 特征行 {features} · 评价面板行 {evaluations} · 仅描述性统计",
        "open_error": "无法读取所选 manifest：", "loaded": "图表已加载。", "unavailable": "Plotly/离线图表依赖不可用；不会以占位图冒充结果。",
        "web_error": "本地 WebEngine 未能载入图表文件", "dom_error": "图表 DOM 未就绪",
        "superseded": "输入已更改；当前运行结果已丢弃，请用新输入重新运行。",
    },
    "ja_JP": {
        "title": "ファクター診断 · RESEARCH-ONLY", "intro": "明示的に選択した凍結ローカルデータのみを使用します。IC、分位、カバレッジ、回転率を表示します。戦略NAVや投資結論ではありません。",
        "manifest": "凍結データマニフェスト", "pick": "マニフェストを選択…", "factor": "価格モメンタム特徴量（窓 / 方向 / ウェイト）", "window_fast": "短期窓", "window_slow": "長期窓", "direction": "方向", "positive": "正方向", "negative": "逆方向",
        "weight": "ウェイト", "normalization": "横断面標準化", "rank": "順位標準化", "zscore": "Z-score",
        "horizon": "将来ラベル期間（営業日）", "minimum": "最小横断面数", "quantiles": "分位数グループ数",
        "run": "ファクター診断を実行", "no_manifest": "データセンターから凍結manifestを選択してください。フォルダー自動検索やダウンロードはしません。",
        "selected": "明示的なローカル入力を選択済み。過去の可視時刻は未検証で、レポートはRESEARCH-ONLYです。",
        "running": "特徴量と独立ラベルパネルをバックグラウンド計算中…", "building": "計算完了。三言語のローカルチャートを生成中…",
        "loading": "チャートをローカルで読み込み中…", "ready": "6種類のチャートを読み込みました。注文やNAVは含まれません。",
        "failed": "ファクター研究に失敗しました：", "chart_failed": "計算は完了しましたが、チャートを利用できません：", "recipe_error": "設定が無効です：",
        "summary": "シグナル日：{start} ～ {end} · 特徴量行 {features} · 評価パネル行 {evaluations} · 記述統計のみ",
        "open_error": "選択したmanifestを読み取れません：", "loaded": "チャートを読み込みました。", "unavailable": "Plotly/オフライン描画依存を利用できません。プレースホルダーを結果として表示しません。",
        "web_error": "ローカル WebEngine がチャートファイルを読み込めません", "dom_error": "チャート DOM が準備できません",
        "superseded": "入力が変更されたため、実行結果を破棄しました。新しい入力で再実行してください。",
    },
    "en_US": {
        "title": "Factor diagnostics · RESEARCH-ONLY", "intro": "Uses only an explicitly selected frozen local dataset. Shows IC, quantiles, coverage, and turnover diagnostics; not strategy NAV or an investment conclusion.",
        "manifest": "Frozen data manifest", "pick": "Choose manifest…", "factor": "Price-momentum features (window / direction / weight)", "window_fast": "Short window", "window_slow": "Long window", "direction": "Direction", "positive": "Positive", "negative": "Negative",
        "weight": "Weight", "normalization": "Cross-sectional normalization", "rank": "Rank normalization", "zscore": "Z-score",
        "horizon": "Forward-label horizon (sessions)", "minimum": "Minimum cross-section", "quantiles": "Quantile groups",
        "run": "Run factor diagnostics", "no_manifest": "Select a frozen manifest from Data Center first. No folder scanning or downloads occur.",
        "selected": "Explicit local input selected. Historical visibility is unverified; report is RESEARCH-ONLY.",
        "running": "Calculating features and the separately stored label panel in the background…", "building": "Calculation finished; building local charts in all three languages…",
        "loading": "Chart files are ready; loading them locally…", "ready": "All six chart types are loaded. The report contains no strategy orders or NAV.",
        "failed": "Factor research failed: ", "chart_failed": "Calculation completed, but charts are unavailable: ", "recipe_error": "Invalid recipe: ",
        "summary": "Signal dates: {start} to {end} · feature rows {features} · evaluation rows {evaluations} · descriptive only",
        "open_error": "Could not read the selected manifest: ", "loaded": "Charts loaded.", "unavailable": "Plotly/offline chart dependencies are unavailable; no placeholder chart is presented as a result.",
        "web_error": "The local WebEngine could not load the chart file", "dom_error": "Chart DOM did not become ready",
        "superseded": "The input changed while this run was active. Its result was discarded; run again with the new input.",
    },
}


class _FactorWorker(QObject):
    completed = Signal(object, object, str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, workspace, manifest, recipe):
        super().__init__()
        self.workspace = str(workspace)
        self.manifest = str(manifest)
        self.recipe = copy.deepcopy(recipe)

    @Slot()
    def run(self):
        try:
            from .research_application import ResearchApplicationService
            from .factor_report_dashboard import build_factor_dashboard

            service = ResearchApplicationService(self.workspace)
            report = service.run_factor_diagnostics(self.manifest, self.recipe)
            output = Path(report["artifacts"]["contract"]).parent
            dashboards = {}
            render_error = ""
            try:
                for language in ("zh_CN", "ja_JP", "en_US"):
                    dashboards[language] = build_factor_dashboard(report, output, language)
            except Exception as exc:
                render_error = f"{type(exc).__name__}: {exc}"
            self.completed.emit(report, dashboards, render_error)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class FactorResearchPanel(QGroupBox):
    """A non-blocking factor workflow embedded in the user-facing data center."""

    def __init__(self, workspace, language="zh_CN", parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace).resolve()
        self.language = language if language in _LANG else "zh_CN"
        self.manifest_path: Path | None = None
        self.report = None
        self.dashboard_paths: dict[str, str] = {}
        self._busy = False
        self._closed = False
        self._input_generation = 0
        self._active_generation = None
        self._active_manifest = None
        self._run_superseded = False
        self._thread = None
        self._worker = None
        self._dom_attempts = 0
        self._last_dom_result = None
        self.setProperty("ownTranslation", True)

        layout = QVBoxLayout(self)
        self.intro = label("", "subtleText"); self.intro.setWordWrap(True); layout.addWidget(self.intro)
        self.manifest_edit = QLineEdit(); self.manifest_edit.setReadOnly(True)
        self.manifest_button = QPushButton(); self.manifest_button.clicked.connect(self._pick_manifest)
        manifest_row = QWidget(); row = QHBoxLayout(manifest_row); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.manifest_edit, 1); row.addWidget(self.manifest_button)
        self.form = QFormLayout()
        self.form_labels = {}
        for key in ("manifest",):
            self.form_labels[key] = QLabel()
        self.form.addRow(self.form_labels["manifest"], manifest_row)

        self.fast_window = self._spin(2, 500, 20)
        self.slow_window = self._spin(2, 500, 60)
        self.fast_weight = self._weight(0.5); self.slow_weight = self._weight(0.5)
        self.fast_direction = QComboBox(); self.slow_direction = QComboBox()
        for control in (self.fast_direction, self.slow_direction):
            control.addItem("", 1); control.addItem("", -1)
        self.horizon = self._spin(1, 252, 5)
        self.minimum_cross_section = self._spin(3, 10000, 3)
        self.quantiles = self._spin(2, 20, 3)
        self.normalization = QComboBox(); self.normalization.addItem("", "rank"); self.normalization.addItem("", "zscore")
        self.window_labels = [QLabel(), QLabel()]
        self._field_rows = {}
        self._field_rows["factor_fast"] = self._row(self.window_labels[0], self.fast_window,
            QLabel("·"), self.fast_direction, QLabel("·"), self.fast_weight)
        self._field_rows["factor_slow"] = self._row(self.window_labels[1], self.slow_window,
            QLabel("·"), self.slow_direction, QLabel("·"), self.slow_weight)
        self._field_rows["horizon"] = self.horizon
        self._field_rows["minimum"] = self.minimum_cross_section
        self._field_rows["quantiles"] = self.quantiles
        self._field_rows["normalization"] = self.normalization
        for key in ("factor", "horizon", "minimum", "quantiles", "normalization"):
            self.form_labels[key] = QLabel()
            if key == "factor":
                self.form.addRow(self.form_labels[key], self._field_rows["factor_fast"])
                self.form.addRow(QLabel(), self._field_rows["factor_slow"])
            else:
                self.form.addRow(self.form_labels[key], self._field_rows[key])
        layout.addLayout(self.form)

        self.run_button = QPushButton(); self.run_button.clicked.connect(self.start)
        layout.addWidget(self.run_button)
        self.status = label("", "detailText"); self.status.setWordWrap(True); self.status.setProperty("ownTranslation", True)
        layout.addWidget(self.status)
        self.view = QWebEngineView(self); self.view.setMinimumHeight(330); layout.addWidget(self.view, 1)
        self.view.loadFinished.connect(self._load_finished)
        self._dom_timer = QTimer(self); self._dom_timer.setInterval(250); self._dom_timer.timeout.connect(self._poll_dom)
        self._summary_template = ""
        self.set_language(self.language)
        self._update_actions()

    @staticmethod
    def _spin(low, high, value):
        control = QSpinBox(); control.setRange(low, high); control.setValue(value); return control

    @staticmethod
    def _weight(value):
        control = QDoubleSpinBox(); control.setRange(0.0, 1.0); control.setSingleStep(0.1); control.setDecimals(3); control.setValue(value)
        return control

    @staticmethod
    def _row(*controls):
        from PySide6.QtWidgets import QHBoxLayout
        widget = QWidget(); row = QHBoxLayout(widget); row.setContentsMargins(0, 0, 0, 0)
        for control in controls: row.addWidget(control)
        return widget

    @property
    def busy(self):
        return self._busy

    def set_manifest(self, path):
        candidate = Path(path).expanduser().resolve() if path else None
        candidate = candidate if candidate and candidate.is_file() else None
        if candidate == self.manifest_path:
            self._update_actions()
            return
        self._input_generation += 1
        if candidate != self.manifest_path:
            self.report = None
            self.dashboard_paths = {}
            self._summary_template = ""
            self._dom_timer.stop()
            self.view.setHtml("<html><body style='background:#0d1117;color:#e6edf3'></body></html>")
        self.manifest_path = candidate
        self.manifest_edit.setText(str(self.manifest_path) if self.manifest_path else "")
        if self._busy:
            self._run_superseded = True
            self.status.setText(_LANG[self.language]["superseded"])
        elif self.manifest_path:
            self.status.setText(_LANG[self.language]["selected"])
        else:
            self.status.setText(_LANG[self.language]["no_manifest"])
        self._update_actions()

    def clear_manifest(self):
        self.set_manifest(None)

    def set_language(self, language):
        self.language = language if language in _LANG else "zh_CN"
        text = _LANG[self.language]
        self.setTitle(text["title"])
        self.intro.setText(text["intro"])
        self.manifest_button.setText(text["pick"])
        self.form_labels["manifest"].setText(text["manifest"])
        for key, label_widget in self.form_labels.items():
            if key == "factor": label_widget.setText(text["factor"])
            elif key in {"horizon", "minimum", "quantiles", "normalization"}: label_widget.setText(text[key])
        self.window_labels[0].setText(text["window_fast"])
        self.window_labels[1].setText(text["window_slow"])
        for control in (self.fast_direction, self.slow_direction):
            control.setItemText(0, text["positive"]); control.setItemText(1, text["negative"])
        self.normalization.setItemText(0, text["rank"]); self.normalization.setItemText(1, text["zscore"])
        self.run_button.setText(text["run"])
        self.fast_weight.setPrefix(text["weight"] + " ")
        self.slow_weight.setPrefix(text["weight"] + " ")
        self.fast_direction.setAccessibleName(text["direction"] + " · " + text["window_fast"])
        self.slow_direction.setAccessibleName(text["direction"] + " · " + text["window_slow"])
        self.fast_weight.setAccessibleName(text["weight"] + " · " + text["window_fast"])
        self.slow_weight.setAccessibleName(text["weight"] + " · " + text["window_slow"])
        if self.report and self.language in self.dashboard_paths:
            dates = self.report.get("dates") or []
            self._summary_template = text["summary"].format(
                start=dates[0] if dates else "—", end=dates[-1] if dates else "—",
                features=self.report.get("feature_row_count", 0),
                evaluations=self.report.get("evaluation_row_count", 0))
            self._load_dashboard(self.language)
        elif self._busy and self._run_superseded:
            self.status.setText(text["superseded"])
        elif not self.manifest_path and not self._busy:
            self.status.setText(text["no_manifest"])
        self._update_actions()

    def recipe(self):
        from .factor_research import validate_recipe

        recipe = copy.deepcopy(DEFAULT_RECIPE)
        fast, slow = self.fast_window.value(), self.slow_window.value()
        if fast == slow:
            raise ValueError("factor windows must be different")
        if self.fast_weight.value() == 0 and self.slow_weight.value() == 0:
            raise ValueError("at least one factor weight must be nonzero")
        recipe["factors"] = [{"id": "price_momentum", "windows": [fast, slow]}]
        recipe["label"]["horizon_sessions"] = self.horizon.value()
        recipe["minimum_cross_section"] = self.minimum_cross_section.value()
        recipe["quantiles"] = self.quantiles.value()
        recipe["composition"]["normalization"] = str(self.normalization.currentData())
        fast_sign = int(self.fast_direction.currentData()); slow_sign = int(self.slow_direction.currentData())
        recipe["composition"]["weights"] = {
            f"price_momentum_{fast}": self.fast_weight.value() * fast_sign,
            f"price_momentum_{slow}": self.slow_weight.value() * slow_sign,
        }
        return validate_recipe(recipe)

    def _pick_manifest(self):
        path, _ = QFileDialog.getOpenFileName(self, _LANG[self.language]["pick"],
            str(self.manifest_path.parent if self.manifest_path else self.workspace), "Manifest JSON (*.json)")
        if path:
            self.set_manifest(path)

    def _update_actions(self):
        self.run_button.setEnabled(bool(self.manifest_path and not self._busy))
        for widget in (self.manifest_button, self.fast_window, self.slow_window, self.fast_weight,
                       self.slow_weight, self.fast_direction, self.slow_direction, self.horizon,
                       self.minimum_cross_section, self.quantiles, self.normalization):
            widget.setEnabled(not self._busy)

    def start(self):
        if self._busy or not self.manifest_path:
            return False
        try:
            recipe = self.recipe()
        except Exception as exc:
            self.status.setText(_LANG[self.language]["recipe_error"] + str(exc))
            return False
        self._busy = True; self.report = None; self.dashboard_paths = {}
        self._active_generation = self._input_generation
        self._active_manifest = self.manifest_path
        self._run_superseded = False
        self._update_actions(); self._dom_timer.stop()
        self.view.setHtml("<html><body style='background:#0d1117;color:#e6edf3'>RESEARCH-ONLY</body></html>")
        self.status.setText(_LANG[self.language]["running"])
        self._thread = QThread(self)
        self._worker = _FactorWorker(self.workspace, self.manifest_path, recipe)
        thread = self._thread
        worker = self._worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda current=thread: self._thread_finished(current))
        thread.start()
        return True

    @Slot(object, object, str)
    def _completed(self, report, dashboards, render_error):
        if self._closed:
            return
        if (self._active_generation != self._input_generation
                or self._active_manifest != self.manifest_path):
            self._run_superseded = True
            return
        self.report = report; self.dashboard_paths = {key: str(item["path"]) for key, item in dashboards.items()}
        dates = report.get("dates") or []
        self._summary_template = _LANG[self.language]["summary"].format(
            start=dates[0] if dates else "—", end=dates[-1] if dates else "—",
            features=report.get("feature_row_count", 0), evaluations=report.get("evaluation_row_count", 0))
        if render_error or not self.dashboard_paths:
            self.status.setText(_LANG[self.language]["chart_failed"] + (render_error or _LANG[self.language]["unavailable"]))
            return
        self.status.setText(self._summary_template + "\n" + _LANG[self.language]["loading"])
        self._load_dashboard(self.language)

    @Slot(str)
    def _failed(self, reason):
        if (not self._closed and self._active_generation == self._input_generation
                and self._active_manifest == self.manifest_path):
            self.status.setText(_LANG[self.language]["failed"] + reason)

    def _load_dashboard(self, language):
        path = self.dashboard_paths.get(language)
        if not path or self._closed:
            return
        self._dom_timer.stop(); self._dom_attempts = 0; self._last_dom_result = None
        self.view.load(QUrl.fromLocalFile(path))
        self.status.setText((self._summary_template + "\n") + _LANG[self.language]["loading"])

    def _load_finished(self, ok):
        if self._closed or self._run_superseded:
            return
        if not ok:
            self.status.setText(_LANG[self.language]["chart_failed"] + _LANG[self.language]["web_error"])
            return
        self._dom_attempts = 0
        self._dom_timer.start()

    def _poll_dom(self):
        if self._closed or self._run_superseded or not self.view:
            self._dom_timer.stop(); return
        self._dom_attempts += 1
        self.view.page().runJavaScript(
            "JSON.stringify({plots:document.querySelectorAll('.plotly-graph-div').length,ready:typeof Plotly})",
            self._dom_checked)
        if self._dom_attempts > 40:
            self._dom_timer.stop()
            detail = f"{_LANG[self.language]['dom_error']} ({self._last_dom_result!r})"
            self.status.setText(_LANG[self.language]["chart_failed"] + detail)

    def _dom_checked(self, result):
        if self._closed or self._run_superseded:
            return
        self._last_dom_result = result
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (TypeError, json.JSONDecodeError):
                return
        if not isinstance(result, dict):
            return
        if result.get("ready") == "object" and int(result.get("plots", 0)) == 6:
            self._dom_timer.stop()
            self.status.setText((self._summary_template + "\n" if self._summary_template else "") + _LANG[self.language]["ready"])

    def _thread_finished(self, thread):
        # A queued completion callback can arrive before QThread.finished.
        # Keep the form locked until this exact worker thread has exited.
        if thread is not self._thread:
            thread.deleteLater()
            return
        self._thread = None; self._worker = None
        self._busy = False
        if not self._closed:
            if self._run_superseded:
                self.status.setText(_LANG[self.language]["superseded"])
            self._update_actions()
        self._active_generation = None; self._active_manifest = None
        self._run_superseded = False
        thread.deleteLater()

    def closeEvent(self, event):
        self._closed = True; self._dom_timer.stop()
        super().closeEvent(event)


__all__ = ["FactorResearchPanel"]
