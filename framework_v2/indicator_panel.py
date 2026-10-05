"""Asynchronous ProductWorkbench price-indicator research panel."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import time
import uuid
from datetime import datetime, timezone
import math

from PySide6.QtCore import QObject, QRunnable, Qt, Signal, Slot, QThreadPool, QProcess, QProcessEnvironment, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .indicator_research import IndicatorRun, calculate_talib_indicators
from .research_runtime import resolve_extension_runtime
from .workbench_widgets import DataTable


_WORKER_ENVIRONMENT_KEYS = frozenset({
    "SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
})


def _isolated_worker_environment(project_root: Path, runtime_paths) -> QProcessEnvironment:
    """Build a minimal child environment without inheriting user secrets or hooks."""
    inherited = QProcessEnvironment.systemEnvironment()
    environment = QProcessEnvironment()
    for name in inherited.keys():
        if name.upper() in _WORKER_ENVIRONMENT_KEYS:
            environment.insert(name, inherited.value(name))
    worker_paths = [str(project_root), *(str(path) for path in runtime_paths)]
    environment.insert("PYTHONPATH", os.pathsep.join(worker_paths))
    environment.insert("PYTHONIOENCODING", "utf-8")
    environment.insert("PYTHONDONTWRITEBYTECODE", "1")
    return environment


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _IndicatorTask(QRunnable):
    """Legacy in-process TA-Lib route; its public parameters remain compatible."""
    def __init__(self, manifest: str, code: str, sma_period: int, rsi_period: int,
                 output_dir: str, atr_period: int = 14):
        super().__init__()
        self.manifest, self.code = manifest, code
        self.sma_period, self.rsi_period, self.atr_period = sma_period, rsi_period, atr_period
        self.output_dir = Path(output_dir)
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            manifest_path = Path(self.manifest).resolve(strict=True)
            before = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            local_identity = None
            if manifest.get("kind") == "kabuforge_local_research_bars":
                from .local_cache import load_research_bars
                selection = manifest.get("selection") or {}
                duplicate_policy = selection.get("duplicate_policy", "reject")
                known_halt_policy = selection.get("known_halt_policy", "reject")
                loaded = load_research_bars(manifest_path, codes=selection.get("requested_codes", ()),
                    start_date=selection.get("start_date", ""), end_date=selection.get("end_date", ""),
                    price_basis=selection.get("price_basis", ""), duplicate_policy=duplicate_policy,
                    known_halt_policy=known_halt_policy)
                bars = loaded.bars.to_dict(orient="records")
                basis = loaded.selection["price_basis"]
                for row in bars:
                    row["adjustment_close"] = row["selected_price"] if basis == "adjusted" else None
                source_kind = f"Frozen local research input ({basis}; PIT unverified)"
                local_identity = {"manifest_sha256": loaded.source["source_sha256"],
                    "selected_data_sha256": loaded.selected_data_sha256,
                    "selection_identity_sha256": loaded.identity_sha256,
                    "pinned_identity_sha256": loaded.source["details"]["pinned_identity_sha256"],
                    "price_basis": basis, "coverage": loaded.coverage}
            else:
                from .data_connection import load_bars
                bars = load_bars(manifest_path)
                source_kind = "J-Quants completed manifest; historical visibility unverified"
            result = calculate_talib_indicators(bars, self.code, sma_period=self.sma_period,
                rsi_period=self.rsi_period, atr_period=self.atr_period, source_kind=source_kind)
            if local_identity is not None:
                from .local_cache import load_research_bars
                selection = manifest.get("selection") or {}
                after_load = load_research_bars(manifest_path, codes=selection.get("requested_codes", ()),
                    start_date=selection.get("start_date", ""), end_date=selection.get("end_date", ""),
                    price_basis=selection.get("price_basis", ""),
                    duplicate_policy=selection.get("duplicate_policy", "reject"),
                    known_halt_policy=selection.get("known_halt_policy", "reject"))
                if after_load.selected_data_sha256 != local_identity["selected_data_sha256"]:
                    raise ValueError("Frozen local market input changed during indicator calculation")
            after = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            if before != after:
                raise ValueError("The source manifest changed while indicators were calculated")
            self.output_dir.mkdir(parents=True, exist_ok=True)
            run_id = uuid.uuid4().hex
            artifact_path = self.output_dir / f"indicator-{run_id}.json"
            payload = _artifact_payload(result, manifest_path, after, local_identity, run_id)
            encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
            with artifact_path.open("xb") as stream:
                stream.write(encoded)
            self.signals.finished.emit({"result": result, "manifest": str(manifest_path),
                "manifest_sha256": after, "artifact_path": str(artifact_path),
                "artifact_sha256": hashlib.sha256(encoded).hexdigest()})
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


def _artifact_payload(result: IndicatorRun, manifest_path: Path, manifest_sha: str,
                      source_identity: dict | None, run_id: str) -> dict:
    implementation = Path(__file__).with_name("indicator_research.py")
    return {
        "schema": "kabuforge_indicator_research", "schema_version": 2, "run_id": run_id,
        "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "source_manifest": str(manifest_path), "source_manifest_sha256": manifest_sha,
        "source_kind": result.source_kind, "source_identity": source_identity,
        "security_code": result.code, "input_sha256": result.input_sha256,
        "price_field": result.price_field, "atr_price_field": result.atr_price_field,
        "parameters": {"sma_period": result.sma_period, "rsi_period": result.rsi_period,
            "macd": {"fast": 12, "slow": 26, "signal": 9}, "atr_period": result.atr_period},
        "engine": {"name": result.engine_name, "version": result.talib_version,
            "python_version": platform.python_version(),
            "implementation_sha256": hashlib.sha256(implementation.read_bytes()).hexdigest(),
            "seed_semantics": _seed_semantics(result.engine_name, result.sma_period,
                                                result.rsi_period, result.atr_period, result.atr_price_field)},
        "rows": result.rows,
    }


def _seed_semantics(engine: str, sma: int, rsi: int, atr: int, atr_basis: str) -> dict:
    if engine == "pandas-ta":
        return {"sma": f"pandas-ta native SMA rolling window length={sma}; initial warm-up is null",
            "rsi": (f"pandas-ta RSI length={rsi}, drift=1; gains/losses use RMA/Wilder alpha=1/length, "
                    "ewm adjust=False without SMA seed; RSI=100*avg_gain/(avg_gain+abs(avg_loss))"),
            "macd": ("pandas-ta MACD fast=12/slow=26/signal=9; EMA presma=True seeds each span with its initial "
                    "span SMA then ewm adjust=False; native warm-up retained"),
            "atr": (f"pandas-ta native ATR length={atr}, talib=False, true range with drift=1; "
                    "RMA/Wilder alpha=1/length with presma=True (initial length-value SMA seed, then recursive RMA); "
                    f"native warm-up retained; {atr_basis}"),
            "gaps": "all source dates retained; warm-up NaN serialized null; no interpolation"}
    return {"sma": f"TA-Lib SMA timeperiod={sma}; native lookback retained",
        "rsi": f"TA-Lib RSI timeperiod={rsi}; native lookback retained",
        "macd": "TA-Lib MACD (12,26,9); native lookback retained",
        "atr": f"TA-Lib ATR timeperiod={atr}; {atr_basis}",
        "gaps": "all source dates retained; warm-up NaN serialized null; no interpolation"}


def _code_matches(requested: str, resolved: str) -> bool:
    return resolved == requested or (len(requested) == 4 and len(resolved) == 5 and resolved.startswith(requested))


class IndicatorChart(QWidget):
    """Small line chart that preserves dates and breaks lines at null warm-ups."""
    def __init__(self, title: str, unit: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.language = "zh_CN"
        self.dates: list[str] = []
        self.series: list[tuple[str, list[float | None]]] = []
        self.series_styles: list[str] = []
        self.setMinimumHeight(185)
        self.setAccessibleName(title)

    def set_series(self, dates, series):
        dates = list(dates)
        normalized = []
        styles = []
        for item in series:
            if len(item) == 2:
                name, values = item
                style = "line"
            elif len(item) == 3:
                name, values, style = item
                if style not in {"line", "bar"}:
                    raise ValueError("chart style must be line or bar")
            else:
                raise ValueError("chart series require a name, values, and optional style")
            values = list(values)
            if len(values) != len(dates):
                raise ValueError("chart series must preserve every source date")
            for value in values:
                if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(float(value))):
                    raise ValueError("chart values must be finite numbers or null warm-ups")
            normalized.append((str(name), values))
            styles.append(style)
        self.dates, self.series = dates, normalized
        self.series_styles = styles
        self.update()

    def _legend_layout(self, width: int):
        """Lay legends below the title and reserve plot space as labels wrap."""
        metrics = self.fontMetrics()
        positions = []
        x, y = 14, 34
        available_width = max(1, width - 28)
        for name, _ in self.series:
            marker_width = 22
            natural = metrics.horizontalAdvance(name)
            item_width = min(available_width, marker_width + natural + 18)
            if positions and (width < 380 or x + item_width > width - 14):
                x = 14
                y += 20
            label_width = max(1, min(natural, width - x - marker_width - 22))
            positions.append((x, y, marker_width, label_width))
            x += marker_width + label_width + 20
        return positions, max(64, y + 20)

    def _y_range(self, finite_values: list[float]) -> tuple[float, float]:
        """Return the display range, keeping RSI on its conventional fixed scale."""
        if self.unit == "0–100":
            return 0.0, 100.0
        low, high = min(finite_values), max(finite_values)
        if "bar" in self.series_styles:
            low, high = min(low, 0.0), max(high, 0.0)
        pad = max((high - low) * 0.12, abs(high) * 0.001, 1e-8)
        return low - pad, high + pad

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = getattr(self, "brand_palette", {})
        bg = QColor(palette.get("surface", "#11151C"))
        fg = QColor(palette.get("text", "#E9ECF2"))
        muted = QColor(palette.get("text-muted", "#9AA4B2"))
        painter.fillRect(self.rect(), bg)
        title_font = painter.fontMetrics()
        unit_width = title_font.horizontalAdvance(self.unit)
        title_width = max(0, self.width() - unit_width - 44)
        painter.setPen(fg)
        painter.drawText(QRectF(14, 3, title_width, 25), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         title_font.elidedText(self.title, Qt.TextElideMode.ElideRight, title_width))
        painter.setPen(muted)
        painter.drawText(QRectF(max(14, self.width() - unit_width - 14), 3, unit_width, 25),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.unit)
        legend_positions, plot_top = self._legend_layout(self.width())
        finite = [float(value) for _, values in self.series for value in values if value is not None]
        if not finite:
            painter.drawText(14, plot_top + 18, {"zh_CN": "运行后显示 · 预热期保留空值", "ja_JP": "実行後に表示 · ウォームアップ値は空欄のまま",
                "en_US": "Shown after run · warm-up values remain null"}.get(self.language, "Run to view"))
            return
        low, high = self._y_range(finite)
        left, top, right, bottom = 66, plot_top, max(90, self.width()-18), max(plot_top + 30, self.height()-30)
        for index in range(4):
            y = top + (bottom-top)*index/3
            value = high - (high-low)*index/3
            painter.setPen(QColor(palette.get("border", "#252B36")))
            painter.drawLine(left, int(y), right, int(y))
            painter.setPen(muted)
            painter.drawText(2, int(y)+4, f"{value:.2f}")
        colors = [QColor(palette.get("info", "#8DB2FF")), QColor(palette.get("warning", "#FFB340")),
                  QColor(palette.get("positive", "#62D6A5"))]
        zero_y = bottom - (0.0-low)/(high-low)*(bottom-top)
        for series_index, (name, values) in enumerate(self.series):
            color = colors[series_index % len(colors)]
            style = self.series_styles[series_index]
            painter.setPen(QPen(color, 2))
            if style == "bar":
                spacing = (right-left)/max(1, len(self.dates)-1)
                bar_width = max(1.0, min(12.0, spacing * 0.68))
                painter.setBrush(color)
                for index, value in enumerate(values):
                    if value is None:
                        continue
                    x = left + (right-left)*index/max(1, len(self.dates)-1)
                    y = bottom - (float(value)-low)/(high-low)*(bottom-top)
                    painter.drawRect(QRectF(x - bar_width/2, min(y, zero_y), bar_width,
                                            max(1.0, abs(zero_y-y))))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                continue
            segment = []
            def draw_segment(points):
                if len(points) == 1:
                    painter.drawEllipse(points[0], 2.5, 2.5)
                elif len(points) > 1:
                    painter.drawPolyline(QPolygonF(points))
            for index, value in enumerate(values):
                if value is None:
                    draw_segment(segment); segment = []; continue
                x = left + (right-left)*index/max(1, len(self.dates)-1)
                y = bottom - (float(value)-low)/(high-low)*(bottom-top)
                segment.append(QPointF(x, y))
            draw_segment(segment)
        for series_index, (name, _) in enumerate(self.series):
            x, y, marker_width, label_width = legend_positions[series_index]
            color = colors[series_index % len(colors)]
            painter.setPen(QPen(color, 2))
            if self.series_styles[series_index] == "bar":
                painter.setBrush(color)
                painter.drawRect(QRectF(x, y + 3, 10, 10))
                painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                painter.drawLine(x, y + 8, x + 15, y + 8)
            painter.setPen(color)
            painter.drawText(QRectF(x + marker_width, y, label_width, 18),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             title_font.elidedText(name, Qt.TextElideMode.ElideRight, label_width))
        painter.setPen(muted)
        if self.dates:
            painter.drawText(left, self.height()-7, self.dates[0])
            painter.drawText(max(left, right-90), self.height()-7, self.dates[-1])


class IndicatorResearchPanel(QGroupBox):
    def __init__(self, workspace: str | Path, language: str = "zh_CN", parent: QWidget | None = None):
        super().__init__(parent)
        self.output_dir = Path(workspace) / "indicator_research_runs"
        self.project_root = Path(__file__).resolve().parents[1]
        self.language = language
        self._task: _IndicatorTask | None = None
        self._process: QProcess | None = None
        self._active_snapshot: dict | None = None
        self._process_buffer = bytearray()
        self._process_log: Path | None = None
        self._job_dir: Path | None = None
        self._launch_receipt: dict | None = None
        self._cancel_reason: str | None = None
        self._worker_started_monotonic: float | None = None
        self._completion_written = False
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._worker_timeout)
        self._last_payload: dict | None = None
        self._status_key = "ready"
        self._status_error = ""
        self._closing = False
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._provider_runtimes = {
            provider: resolve_extension_runtime(self.project_root, platform.python_version(),
                sysconfig.get_platform(), operation="indicators", choices={"provider": provider})
            for provider in ("talib", "pandas-ta")
        }
        self._extension_runtime = self._provider_runtimes["talib"]
        self.pandas_ta_ready = bool(self._provider_runtimes["pandas-ta"].get("enabled"))
        root = QVBoxLayout(self)
        self.notice = QLabel(); self.notice.setWordWrap(True); root.addWidget(self.notice)
        self.manifest = QLineEdit(); self.manifest.setReadOnly(True)
        self.browse = QPushButton(); self.browse.clicked.connect(self._browse)
        path_row = QWidget(); path_layout = QHBoxLayout(path_row); path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self.manifest, 1); path_layout.addWidget(self.browse); root.addWidget(path_row)
        form = QFormLayout(); self.form = form
        self.provider = QComboBox()
        self.provider.addItem("TA-Lib", "talib")
        self.provider.addItem("pandas-ta · isolated worker", "pandas_ta")
        self.code = QLineEdit(); self.code.setPlaceholderText("7203")
        self.sma_period = QSpinBox(); self.sma_period.setRange(2, 500); self.sma_period.setValue(20)
        self.rsi_period = QSpinBox(); self.rsi_period.setRange(2, 100); self.rsi_period.setValue(14)
        self.atr_period = QSpinBox(); self.atr_period.setRange(2, 100); self.atr_period.setValue(14)
        self.provider_label = QLabel(); self.code_label = QLabel()
        self.sma_label = QLabel("SMA"); self.rsi_label = QLabel("RSI"); self.atr_label = QLabel("ATR")
        form.addRow(self.provider_label, self.provider); form.addRow(self.code_label, self.code)
        form.addRow(self.sma_label, self.sma_period); form.addRow(self.rsi_label, self.rsi_period)
        form.addRow(self.atr_label, self.atr_period); root.addLayout(form)
        self.run_button = QPushButton(); self.run_button.clicked.connect(self.run)
        self.cancel_button = QPushButton(); self.cancel_button.clicked.connect(self.cancel_worker)
        self.cancel_button.hide()
        buttons = QHBoxLayout(); buttons.addWidget(self.run_button); buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)
        self.status = QLabel(); self.status.setWordWrap(True); root.addWidget(self.status)
        self.dependency = self._provider_runtimes["talib"]
        self.dependency_ready = bool(self.dependency.get("enabled"))
        self.chart = IndicatorChart("Close / SMA", "JPY/share")
        self.rsi_chart = IndicatorChart("RSI", "0–100")
        self.macd_chart = IndicatorChart("MACD", "JPY/share")
        self.atr_chart = IndicatorChart("ATR", "JPY/share")
        self.table = DataTable("Indicator research")
        for chart in (self.chart, self.rsi_chart, self.macd_chart, self.atr_chart, self.table):
            root.addWidget(chart)
        self.code.textChanged.connect(self._invalidate_result)
        self.sma_period.valueChanged.connect(self._invalidate_result)
        self.rsi_period.valueChanged.connect(self._invalidate_result)
        self.atr_period.valueChanged.connect(self._invalidate_result)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.set_language(language)
        self._update_enabled_state()

    def _text(self, zh: str, ja: str, en: str) -> str:
        return {"zh_CN": zh, "ja_JP": ja, "en_US": en}.get(self.language, zh)

    def set_language(self, language: str) -> None:
        self.language = language
        self._refresh_language()

    def _refresh_language(self) -> None:
        self.setTitle(self._text("技术指标研究 · TA-Lib / pandas-ta", "テクニカル指標研究 · TA-Lib / pandas-ta",
                                 "Technical indicator research · TA-Lib / pandas-ta"))
        self.notice.setText(self._text(
            "选择完成的本地行情清单，计算 SMA、RSI、MACD 与 ATR。ATR 只使用同一价格口径的 OHLC；指标仅供研究，不生成策略或订单，历史 PIT 未认证。pandas-ta 在隔离进程运行。",
            "完了したローカル株価マニフェストを選び、SMA・RSI・MACD・ATR を計算します。ATR は同一価格基準の OHLC のみを使用します。研究表示のみで、戦略・注文は生成せず、履歴 PIT は未認証です。pandas-ta は隔離プロセスで実行します。",
            "Choose a completed local price manifest for SMA, RSI, MACD, and ATR. ATR uses OHLC from one consistent price basis. Research display only; no strategy or order is created, and historical PIT is unverified. pandas-ta runs in an isolated process."))
        self.manifest.setPlaceholderText(self._text("选择已完成的本地行情清单", "完了したローカル株価マニフェストを選択", "Choose a completed local price manifest"))
        self.browse.setText(self._text("浏览", "参照", "Browse"))
        self.provider_label.setText(self._text("计算引擎", "計算エンジン", "Provider"))
        self.provider.setItemText(0, "TA-Lib · 隔离进程" if self.language == "zh_CN" else ("TA-Lib · 隔離プロセス" if self.language == "ja_JP" else "TA-Lib · isolated worker"))
        self.provider.setItemText(1, "pandas-ta · 隔离进程" if self.language == "zh_CN" else ("pandas-ta · 隔離プロセス" if self.language == "ja_JP" else "pandas-ta · isolated worker"))
        self.code_label.setText(self._text("证券代码", "銘柄コード", "Security code"))
        self.sma_label.setText(self._text("SMA 周期", "SMA 期間", "SMA period"))
        self.rsi_label.setText(self._text("RSI 周期", "RSI 期間", "RSI period"))
        self.atr_label.setText(self._text("ATR 周期", "ATR 期間", "ATR period"))
        self.run_button.setText(self._text("计算并查看指标", "指標を計算して表示", "Calculate and view indicators"))
        self.cancel_button.setText(self._text("取消计算", "計算をキャンセル", "Cancel calculation"))
        self.chart.title = self._text("价格 / SMA", "価格 / SMA", "Price / SMA")
        self.rsi_chart.title = "RSI"
        self.macd_chart.title = "MACD · " + self._text("线 / 信号 / 柱", "線 / シグナル / ヒストグラム", "line / signal / histogram")
        basis = getattr(self._last_payload.get("result"), "atr_price_field", None) if self._last_payload else None
        if basis:
            basis_label = self._basis_label(basis)
            self.atr_chart.title = self._text("ATR · ", "ATR · ", "ATR · ") + basis_label
        else:
            self.atr_chart.title = self._text("ATR · 同一口径 OHLC", "ATR · 同一基準 OHLC", "ATR · consistent-basis OHLC")
        for chart in (self.chart, self.rsi_chart, self.macd_chart, self.atr_chart):
            chart.language = self.language; chart.setAccessibleName(chart.title); chart.update()
        self.table.name = self._text("技术指标研究", "テクニカル指標研究", "Indicator research")
        self.table.view.setAccessibleName(self.table.name)
        self.table.search.setPlaceholderText(self._text("筛选表格…", "表を絞り込む…", "Filter table…"))
        self.table.search.setAccessibleName(self.table.name + self._text("筛选", "で絞り込み", " filter"))
        self.table.export.setText(self._text("导出 CSV", "CSV をエクスポート", "Export CSV"))
        self.table.export.setToolTip(self._text("导出当前筛选结果", "現在の絞り込み結果を出力", "Export the currently filtered rows"))
        if self._last_payload is not None:
            self._render_result(self._last_payload)
        self._render_status()

    def _provider_id(self) -> str:
        return str(self.provider.currentData())

    def _provider_changed(self, *_):
        provider = "talib" if self._provider_id() == "talib" else "pandas-ta"
        self._extension_runtime = self._provider_runtimes[provider]
        self._invalidate_result()
        self._update_enabled_state()
        if not (self.dependency_ready if self._provider_id() == "talib" else self.pandas_ta_ready):
            self._status_key = "missing_dependency"
            self._render_status()
        elif self._status_key == "missing_dependency":
            self._status_key = "ready"
            self._render_status()

    def _is_busy(self) -> bool:
        return self._task is not None or self._process is not None

    def _invalidate_result(self, *_):
        if self._is_busy():
            return
        self._last_payload = None
        if self._status_key == "completed":
            self._status_key = "ready"
        self._clear_visuals()
        self._render_status()

    def _update_enabled_state(self) -> None:
        provider_ok = self.dependency_ready if self._provider_id() == "talib" else self.pandas_ta_ready
        self.run_button.setEnabled(bool(provider_ok and not self._is_busy()))

    def _render_status(self) -> None:
        if self._status_key == "completed" and self._last_payload is not None:
            result = self._last_payload["result"]
            artifact = self._last_payload.get("artifact_path", "")
            basis = self._basis_label(getattr(result, "atr_price_field", "original raw OHLC"))
            message = self._text(
                f"完成 · {len(result.rows)} 根实际来源日线 · {result.engine_name} {result.talib_version} · SMA{result.sma_period}/RSI{result.rsi_period}/MACD(12,26,9)/ATR{result.atr_period} · 价格列 {result.price_field}；ATR 使用{basis} · SHA-256 {result.input_sha256} · {artifact} · RESEARCH-ONLY / PIT 未认证。",
                f"完了 · 実データ日足 {len(result.rows)} 本 · {result.engine_name} {result.talib_version} · SMA{result.sma_period}/RSI{result.rsi_period}/MACD(12,26,9)/ATR{result.atr_period} · 価格列 {result.price_field}、ATR は{basis} · SHA-256 {result.input_sha256} · {artifact} · RESEARCH-ONLY / PIT 未認証。",
                f"Complete · {len(result.rows)} source daily bars · {result.engine_name} {result.talib_version} · SMA{result.sma_period}/RSI{result.rsi_period}/MACD(12,26,9)/ATR{result.atr_period} · price field {result.price_field}; ATR uses {basis} · SHA-256 {result.input_sha256} · {artifact} · RESEARCH-ONLY / PIT unverified.")
        elif self._status_key == "failed":
            message = self._text("未完成：", "未完了：", "Not completed: ") + self._status_error
        else:
            messages = {
                "ready": ("等待本地计算。", "ローカル計算を待機中。", "Ready for local calculation."),
                "running": ("隔离计算进程运行中；输入已冻结。", "隔離計算プロセス実行中。入力は固定済みです。", "Isolated worker running; inputs are frozen."),
                "cancelled": ("计算已取消；任务目录与日志已保留，可重新开始新任务。", "計算をキャンセルしました。ジョブとログは保存され、新しい実行を開始できます。", "Calculation canceled; job evidence was retained and a new run can start."),
                "timed_out": ("计算超时；任务目录与日志已保留，可重新开始新任务。", "計算がタイムアウトしました。ジョブとログは保存され、新しい実行を開始できます。", "Calculation timed out; job evidence was retained and a new run can start."),
                "missing_manifest": ("请先选择完整的本地行情清单。", "完了したローカル株価マニフェストを選択してください。", "Choose a completed local price manifest first."),
                "missing_code": ("请输入证券代码。", "銘柄コードを入力してください。", "Enter a security code."),
                "missing_dependency": ("当前 Python 环境缺少所选指标引擎所需依赖，尚未运行计算。", "現在の Python 環境に選択した指標エンジンの依存パッケージがありません。計算は実行していません。", "The selected indicator provider dependencies are unavailable in the active Python environment; no calculation ran."),
                "closing": ("正在停止本面板拥有的计算进程。", "このパネルが所有する計算プロセスを停止中。", "Stopping this panel's owned worker."),
            }
            message = self._text(*messages.get(self._status_key, messages["ready"]))
        self.status.setText(message)

    def _clear_visuals(self):
        columns = self._column_names()
        self.table.set_rows([], columns)
        for chart in (self.chart, self.rsi_chart, self.macd_chart, self.atr_chart):
            chart.set_series([], [])

    def _column_names(self):
        result = self._last_payload.get("result") if self._last_payload else None
        basis = getattr(result, "atr_price_field", "original raw OHLC")
        label = self._basis_label(basis)
        return {"zh_CN": ["日期", "代码", "价格", "SMA", "RSI", "MACD", "MACD 信号", "MACD 柱", f"ATR ({label})"],
                "ja_JP": ["日付", "コード", "価格", "SMA", "RSI", "MACD", "MACDシグナル", "MACDヒストグラム", f"ATR ({label})"],
                "en_US": ["Date", "Code", "Price", "SMA", "RSI", "MACD", "MACD signal", "MACD histogram", f"ATR ({label})"]}.get(self.language, [])

    def _basis_label(self, basis: str) -> str:
        adjusted = basis == "adjusted OHLC"
        return self._text("复权 OHLC" if adjusted else "原始 OHLC",
                          "調整後 OHLC" if adjusted else "元 OHLC",
                          "adjusted OHLC" if adjusted else "original raw OHLC")

    def _render_result(self, payload: dict) -> None:
        result = payload["result"]
        rows = list(result.rows)
        columns = self._column_names()
        keys = ["date", "code", "close", "sma", "rsi", "macd", "macd_signal", "macd_histogram", "atr"]
        self.table.set_rows([dict(zip(columns, (row.get(key) for key in keys))) for row in rows], columns)
        dates = [row["date"] for row in rows]
        self.chart.set_series(dates, [(self._text("价格", "価格", "Price"), [row.get("close") for row in rows]),
                                      (f"SMA {result.sma_period}", [row.get("sma") for row in rows])])
        self.rsi_chart.set_series(dates, [("RSI", [row.get("rsi") for row in rows])])
        self.macd_chart.set_series(dates, [("MACD", [row.get("macd") for row in rows]),
            (self._text("信号", "シグナル", "Signal"), [row.get("macd_signal") for row in rows]),
            (self._text("柱", "ヒストグラム", "Histogram"),
             [row.get("macd_histogram") for row in rows], "bar")])
        basis_label = self._basis_label(result.atr_price_field)
        self.atr_chart.title = self._text("ATR · ", "ATR · ", "ATR · ") + basis_label
        self.atr_chart.set_series(dates, [(self.atr_chart.title, [row.get("atr") for row in rows])])

    def set_manifest(self, path: str | Path) -> bool:
        if self._is_busy():
            return False
        self.manifest.setText(str(path))
        self._invalidate_result()
        self._status_key = "ready" if Path(path).is_file() else "missing_manifest"
        self._render_status()
        return True

    def clear_manifest(self) -> bool:
        if self._is_busy():
            return False
        self.manifest.clear(); self._last_payload = None
        self._status_key = "missing_manifest"; self._status_error = ""
        self._clear_visuals(); self._render_status(); return True

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self._text("选择完成的行情清单", "完了した株価マニフェスト", "Choose a completed price manifest"), "", "JSON (*.json)")
        if path:
            self.set_manifest(path)

    def run(self) -> bool:
        if self._is_busy():
            return False
        provider = self._provider_id()
        provider_ready = self.dependency_ready if provider == "talib" else self.pandas_ta_ready
        if not provider_ready:
            self._status_key = "missing_dependency"; self._render_status(); return False
        path = Path(self.manifest.text()).expanduser()
        code = self.code.text().strip()
        if not path.is_file():
            self._status_key = "missing_manifest"; self._render_status(); return False
        if not code:
            self._status_key = "missing_code"; self._render_status(); return False
        params = (int(self.sma_period.value()), int(self.rsi_period.value()), int(self.atr_period.value()))
        snapshot = {"manifest": str(path.resolve()), "code": code, "sma_period": params[0],
                    "rsi_period": params[1], "atr_period": params[2], "provider": provider}
        self._active_snapshot = dict(snapshot)
        self._last_payload = None; self._clear_visuals()
        return self._start_isolated_worker(snapshot)

    def _lock_inputs(self, locked: bool) -> None:
        for widget in (self.provider, self.browse, self.code, self.sma_period, self.rsi_period, self.atr_period):
            widget.setEnabled(not locked)
        self.cancel_button.setVisible(bool(locked and self._process is not None))
        self.cancel_button.setEnabled(bool(locked and self._process is not None and
                                          self._process.state() != QProcess.ProcessState.NotRunning))
        self._update_enabled_state()

    def _start_isolated_worker(self, snapshot: dict) -> bool:
        provider = "talib" if snapshot.get("provider") == "talib" else "pandas-ta"
        runtime = resolve_extension_runtime(self.project_root, platform.python_version(),
            sysconfig.get_platform(), operation="indicators", choices={"provider": provider})
        self._extension_runtime = runtime
        if not runtime.get("enabled"):
            self._active_snapshot = None
            self._status_key = "missing_dependency"; self._render_status(); return False
        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = Path(snapshot["manifest"]).resolve(strict=True)
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        request = {**snapshot, "manifest_sha256": manifest_sha,
                   "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
        request_sha = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:10]
        self._job_dir = self.output_dir / "jobs" / job_id
        self._job_dir.mkdir(parents=True, exist_ok=False)
        worker_output = self._job_dir / "output"
        worker_output.mkdir()
        self._process_buffer = bytearray()
        self._completion_written = False
        self._process_log = self._job_dir / "worker.log"
        self._cancel_reason = None
        process = QProcess(self)
        process.setWorkingDirectory(str(self.project_root))
        environment = _isolated_worker_environment(self.project_root, runtime.get("paths", []))
        process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_worker_output)
        process.started.connect(self._worker_started)
        process.finished.connect(self._worker_finished)
        process.errorOccurred.connect(self._worker_error)
        self._process = process
        self._worker_snapshot = {**snapshot, "job_id": job_id, "job_dir": str(self._job_dir),
                                 "output_dir": str(worker_output), "request_sha256": request_sha,
                                 "manifest_sha256": manifest_sha}
        args = ["-B", "-m", "framework_v2.indicator_research_worker",
                "--project-root", str(self.project_root), "--manifest", snapshot["manifest"],
                "--output-dir", str(worker_output), "--code", snapshot["code"],
                "--sma-period", str(snapshot["sma_period"]), "--rsi-period", str(snapshot["rsi_period"]),
                "--atr-period", str(snapshot["atr_period"]), "--provider", provider]
        self._launch_receipt = {"schema": "kabuforge_indicator_worker_launch", "schema_version": 1,
            "job_id": job_id, "program": sys.executable, "argv": args,
            "pid": None, "process_started_at_utc": None,
            "request": request, "request_sha256": request_sha,
            "source_manifest_sha256": manifest_sha, "output_dir": str(worker_output),
            "log_path": str(self._process_log), "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "network": "not requested; worker has no transport or credential API call",
            "recovery": "retain this job directory; retry only into a new job ID; never overwrite partial outputs"}
        self._write_json_atomic(self._job_dir / "launch.json", self._launch_receipt, create_only=True)
        self._worker_started_monotonic = time.monotonic()
        self._lock_inputs(True); self._status_key = "running"; self._render_status()
        self._timeout_timer.start(300_000)
        process.start(sys.executable, args)
        return True

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict, *, create_only: bool = False) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        if create_only:
            with path.open("xb") as stream:
                stream.write(encoded)
            return
        temporary = path.with_name(path.name + ".pending-" + uuid.uuid4().hex)
        with temporary.open("xb") as stream:
            stream.write(encoded)
        temporary.replace(path)

    @Slot()
    def _worker_started(self):
        if self._launch_receipt is None or self._process is None:
            return
        self._launch_receipt["pid"] = int(self._process.processId())
        self._launch_receipt["process_started_at_utc"] = datetime.now(timezone.utc).isoformat()
        self._write_json_atomic(self._job_dir / "launch.json", self._launch_receipt)

    @Slot()
    def cancel_worker(self):
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return False
        self._cancel_reason = "user_cancelled"
        self.status.setText(self._text("正在停止本任务的隔离进程…", "このジョブの隔離プロセスを停止中…", "Stopping this owned worker…"))
        process.terminate()
        QTimer.singleShot(2000, lambda: process.kill() if self._process is process and
                          process.state() != QProcess.ProcessState.NotRunning else None)
        return True

    @Slot()
    def _worker_timeout(self):
        if self._process is None or self._process.state() == QProcess.ProcessState.NotRunning:
            return
        self._cancel_reason = "worker_timeout_300s"
        self._process.terminate()
        process = self._process
        QTimer.singleShot(2000, lambda: process.kill() if self._process is process and
                          process.state() != QProcess.ProcessState.NotRunning else None)

    @Slot()
    def _read_worker_output(self):
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput())
        self._process_buffer.extend(chunk)
        if self._process_log is not None:
            with self._process_log.open("ab") as stream:
                stream.write(chunk)
        if self._launch_receipt is not None and self._launch_receipt.get("python_worker_pid") is None:
            for line in bytes(self._process_buffer).decode("utf-8", errors="replace").splitlines():
                if line.startswith("INDICATOR_WORKER_STARTED="):
                    try:
                        worker = json.loads(line.split("=", 1)[1])
                    except json.JSONDecodeError:
                        continue
                    self._launch_receipt.update({"python_worker_pid": worker.get("pid"),
                        "python_worker_ppid": worker.get("ppid"),
                        "python_worker_executable": worker.get("executable"),
                        "python_worker_argv": worker.get("orig_argv") or worker.get("argv")})
                    self._write_json_atomic(self._job_dir / "launch.json", self._launch_receipt)
                    break

    def _worker_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            self._worker_finished(-1, QProcess.ExitStatus.CrashExit)

    @Slot(int, QProcess.ExitStatus)
    def _worker_finished(self, exit_code: int, exit_status):
        if self._process is None or self._completion_written:
            return
        self._read_worker_output()
        self._timeout_timer.stop()
        process = self._process
        lines = bytes(self._process_buffer).decode("utf-8", errors="replace").splitlines()
        result = None
        for line in lines:
            if line.startswith("INDICATOR_RESULT="):
                try: result = json.loads(line.split("=", 1)[1])
                except json.JSONDecodeError: pass
        elapsed = (time.monotonic() - self._worker_started_monotonic
                   if self._worker_started_monotonic is not None else None)
        completion = {"schema": "kabuforge_indicator_worker_completion", "schema_version": 1,
            "job_id": self._worker_snapshot.get("job_id") if self._worker_snapshot else None,
            "pid": self._launch_receipt.get("pid") if self._launch_receipt else None,
            "exit_code": int(exit_code),
            "exit_status": "normal" if exit_status == QProcess.ExitStatus.NormalExit else "crash",
            "ended_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3) if elapsed is not None else None,
            "request_sha256": self._worker_snapshot.get("request_sha256") if self._worker_snapshot else None,
            "source_manifest_sha256": self._worker_snapshot.get("manifest_sha256") if self._worker_snapshot else None,
            "input_sha256": result.get("input_sha256") if isinstance(result, dict) else None,
            "output_dir": self._worker_snapshot.get("output_dir") if self._worker_snapshot else None,
            "log_path": str(self._process_log) if self._process_log else None,
            "log_sha256": hashlib.sha256(self._process_log.read_bytes()).hexdigest()
                if self._process_log is not None and self._process_log.is_file() else None,
            "result": result, "cancellation_reason": self._cancel_reason,
            "recovery": "partial files retained; restart uses a fresh task directory"}
        if self._job_dir is not None:
            self._write_json_atomic(self._job_dir / "completion.json", completion, create_only=True)
        self._completion_written = True
        if self._closing:
            if process is not None:
                process.deleteLater()
            self._process = None
            return
        if self._cancel_reason is not None:
            reason = self._cancel_reason
            if process is not None:
                process.deleteLater()
            self._process = None
            self._status_key = "timed_out" if reason.startswith("worker_timeout") else "cancelled"
            self._status_error = ""; self._render_status()
            self._task = None; self._worker_snapshot = None; self._lock_inputs(False)
            return
        if exit_code != 0 or not isinstance(result, dict) or result.get("ok") is not True:
            error = result.get("error") if isinstance(result, dict) else None
            if process is not None:
                process.deleteLater()
            self._process = None
            self._finish_worker_error(error or f"indicator worker exited with code {exit_code}; log: {self._process_log}")
            return
        try:
            artifact_path = Path(result["artifact_path"]).resolve(strict=True)
            expected_output = Path(self._worker_snapshot["output_dir"]).resolve(strict=True)
            if artifact_path.parent != expected_output:
                raise ValueError("worker artifact is outside the dedicated output directory")
            artifact_bytes = artifact_path.read_bytes()
            if hashlib.sha256(artifact_bytes).hexdigest() != result.get("artifact_sha256"):
                raise ValueError("worker artifact SHA-256 does not match its process receipt")
            payload = json.loads(artifact_bytes.decode("utf-8"))
            expected = self._worker_snapshot
            expected_engine = {"talib": "TA-Lib", "pandas_ta": "pandas-ta"}.get(expected.get("provider"))
            if (payload.get("schema") != "kabuforge_indicator_research" or
                    type(payload.get("schema_version")) is not int or payload.get("schema_version") != 2 or payload.get("readiness") != "RESEARCH-ONLY" or
                    payload.get("pit_guarantee") is not False or payload.get("engine", {}).get("name") != expected_engine):
                raise ValueError("worker artifact identity/schema validation failed")
            if not _code_matches(expected["code"], str(payload.get("security_code", ""))):
                raise ValueError("worker artifact security code does not resolve from the frozen request")
            if payload.get("source_manifest_sha256") != expected["manifest_sha256"]:
                raise ValueError("worker artifact source manifest changed from the frozen request")
            parameters = payload.get("parameters", {})
            if any(parameters.get(key) != expected[key] for key in ("sma_period", "rsi_period", "atr_period")):
                raise ValueError("worker artifact indicator parameters differ from the frozen request")
            rows = payload.get("rows")
            dates = [row.get("date") for row in rows] if isinstance(rows, list) else []
            if not dates or len(dates) != len(set(dates)) or dates != sorted(dates):
                raise ValueError("worker artifact dates are missing, duplicated, or out of order")
            engine = payload["engine"]
            run = IndicatorRun(payload["security_code"], payload["source_kind"], False,
                engine["version"], expected["sma_period"], expected["rsi_period"], payload["price_field"],
                payload["input_sha256"], tuple(rows), expected["atr_period"],
                expected_engine, payload["atr_price_field"])
            if process is not None:
                process.deleteLater()
            self._process = None
            self._finished({"result": run, "manifest": payload["source_manifest"],
                "manifest_sha256": payload["source_manifest_sha256"], "artifact_path": str(artifact_path),
                "artifact_sha256": result.get("artifact_sha256"), "worker_log": str(self._process_log)})
        except Exception as exc:
            self._finish_worker_error(f"{type(exc).__name__}: {exc}")
        if self._process is not None:
            self._process.deleteLater(); self._process = None

    def _finish_worker_error(self, message: str):
        self._timeout_timer.stop()
        if self._process is not None:
            self._process.deleteLater(); self._process = None
        self._failed(message)

    @Slot(object)
    def _finished(self, payload: dict) -> None:
        snapshot = self._active_snapshot
        result = payload.get("result") if isinstance(payload, dict) else None
        expected_engine = {"talib": "TA-Lib", "pandas_ta": "pandas-ta"}.get(snapshot.get("provider")) if snapshot else None
        if snapshot is None or result is None or (
                not _code_matches(snapshot["code"], result.code) or snapshot["sma_period"] != result.sma_period or
                snapshot["rsi_period"] != result.rsi_period or snapshot["atr_period"] != result.atr_period or
                expected_engine != result.engine_name):
            self._failed("Inputs changed or result identity does not match the frozen request")
            return
        self._last_payload = payload; self._status_key = "completed"; self._status_error = ""
        self._render_result(payload); self._render_status()
        self._task = None; self._worker_snapshot = None; self._active_snapshot = None
        self._lock_inputs(False)

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._last_payload = None; self._clear_visuals()
        log_suffix = f" · worker log: {self._process_log}" if self._process_log is not None else ""
        self._status_key = "failed"; self._status_error = message + log_suffix; self._render_status()
        self._task = None; self._worker_snapshot = None; self._active_snapshot = None
        self._lock_inputs(False)

    def closeEvent(self, event):
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._closing = True; self._status_key = "closing"; self._render_status()
            owned = self._process
            owned.terminate()
            if not owned.waitForFinished(1500):
                owned.kill()
                if not owned.waitForFinished(1500):
                    self._closing = False
                    event.ignore()
                    return
            if self._process is owned:
                self._worker_finished(owned.exitCode(), owned.exitStatus())
        self._timeout_timer.stop()
        if self._task is not None and not self._pool.waitForDone(1500):
            event.ignore()
            return
        event.accept()
