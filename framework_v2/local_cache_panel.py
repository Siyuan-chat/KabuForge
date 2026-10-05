"""Explicit offline daily-bar selection and immutable research-input freeze."""
from __future__ import annotations

from pathlib import Path
import uuid

from PySide6.QtCore import QObject, QRunnable, QDate, Qt, Signal, Slot, QThreadPool
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)


_TEXT = {
        "zh_CN": {
        "title": "本地行情缓存 · 离线研究输入", "notice": "离线选择你指定的既有文件；覆盖按实际观察日期显示，不推断交易日缺口。",
        "source": "本地输入文件", "browse": "选择文件", "codes": "证券代码（逗号分隔）", "start": "开始日期", "end": "结束日期", "basis": "研究价格口径", "raw": "原始收盘价", "adjusted": "复权收盘价（如有）", "duplicates": "重复行处理", "reject_duplicates": "严格拒绝重复（默认）", "drop_identical": "仅合并完全相同重复行", "duplicate_count": "重复策略 {policy} · 去重前 {input_rows} 行→保留 {retained_rows} 行 · 删除完全相同重复行 {removed} 条；同代码/日期冲突始终拒绝", "run": "验证并冻结输入", "ready": "选择本地文件和研究范围。", "running": "正在验证所选输入并写入新的冻结目录……", "complete": "输入已冻结并复核", "failed": "未完成", "filter": "CSV / Parquet / snapshot / J-Quants 清单 (*.csv *.txt *.parquet *.pq *.json)", "no_source": "请先选择一个本地输入文件。", "bad_codes": "请输入至少一个证券代码。", "coverage": "请求 {requested_start} 至 {requested_end} · {rows} 行 · 观测 {first} 至 {last} · 来源 {kind} · 口径 {basis}", "hash": "源 SHA-256 {source} · 选中数据 SHA-256 {selected} · 冻结身份 {identity}", "pit": "历史可见性未认证；没有推断 available_at。", "frozen": "冻结清单：{path}", "details": "查看来源身份与限制", "backtest_ok": "当前日线回测支持区间内有复权记录且没有拆股调整的数据。", "backtest_blocked": "当前日线回测暂不可用：区间需有复权记录且没有拆股调整；{reason}。指标研究仍可使用。",
    },
    "ja_JP": {
        "title": "ローカル相場キャッシュ · オフライン研究入力", "notice": "指定した既存ファイルをオフラインで選択します。範囲は観測日で表示し、取引日欠損は推定しません。",
        "source": "ローカル入力ファイル", "browse": "ファイルを選択", "codes": "銘柄コード（カンマ区切り）", "start": "開始日", "end": "終了日", "basis": "価格の調整方式", "raw": "未調整終値", "adjusted": "調整後終値（存在する場合）", "duplicates": "重複行の処理", "reject_duplicates": "重複を厳格に拒否（既定）", "drop_identical": "完全一致する重複行のみ統合", "duplicate_count": "方針 {policy} · 重複前 {input_rows} 行→保持 {retained_rows} 行 · 削除した完全一致行 {removed} 行。同一コード/日付の競合は常に拒否", "run": "検証して固定", "ready": "ローカルファイルと研究期間を選択してください。", "running": "入力を検証し、新しい固定ディレクトリへ保存中…", "complete": "入力を固定し、再検証しました", "failed": "未完了", "filter": "CSV / Parquet / snapshot / J-Quants (*.csv *.txt *.parquet *.pq *.json)", "no_source": "ローカル入力ファイルを選択してください。", "bad_codes": "銘柄コードを1つ以上入力してください。", "coverage": "指定 {requested_start} 〜 {requested_end} · {rows} 行 · 観測 {first} 〜 {last} · ソース {kind} · 調整 {basis}", "hash": "ソース SHA-256 {source} · 選択データ SHA-256 {selected} · 固定ID {identity}", "pit": "過去の可視性は未認証です。available_at は推定しません。", "frozen": "固定マニフェスト: {path}", "details": "ソースIDと制限を表示", "backtest_ok": "現在の日足バックテストは、調整記録があり、期間内に株式分割調整がないデータに対応します。", "backtest_blocked": "現在の日足バックテストは利用できません。調整記録が必要で、期間内に株式分割調整がないことが条件です（{reason}）。指標研究には使用できます。",
    },
    "en_US": {
        "title": "Local market cache · offline research input", "notice": "Select an existing local file for offline use. Coverage shows observed dates and does not infer missing sessions.",
        "source": "Local input file", "browse": "Choose file", "codes": "Security codes (comma-separated)", "start": "Start date", "end": "End date", "basis": "Research price basis", "raw": "Raw close", "adjusted": "Adjusted close (when present)", "duplicates": "Duplicate-row policy", "reject_duplicates": "Reject duplicates (default)", "drop_identical": "Drop only fully identical duplicates", "duplicate_count": "Policy {policy} · {input_rows} rows before dedup → {retained_rows} retained · removed {removed} identical rows; conflicting code/date rows are always rejected", "run": "Verify and freeze input", "ready": "Choose a local file and research range.", "running": "Verifying the selected input and writing a new frozen directory…", "complete": "Input frozen and reverified", "failed": "Not completed", "filter": "CSV / Parquet / snapshot / J-Quants (*.csv *.txt *.parquet *.pq *.json)", "no_source": "Choose one local input file first.", "bad_codes": "Enter at least one security code.", "coverage": "Requested {requested_start} to {requested_end} · {rows} rows · observed {first} to {last} · source {kind} · {basis}", "hash": "Source SHA-256 {source} · selected data SHA-256 {selected} · frozen identity {identity}", "pit": "Historical visibility is unverified; available_at was not inferred.", "frozen": "Frozen manifest: {path}", "details": "Show source identity and limitations", "backtest_ok": "The current daily backtest supports data with adjustment records and no split adjustments within the selected range.", "backtest_blocked": "The current daily backtest needs adjustment records and no split adjustments within the selected range ({reason}); indicator research remains available.",
    },
}

_TEXT["zh_CN"].update({
    "halt_label": "排除已核实的2020-10-01东证全日停市空行情",
    "halt_summary": "东证停市排除：{status}",
    "halt_reason": "行情分发系统故障导致东证全市场暂停交易",
    "halt_excluded": "排除 {rows} 行（{date}）；{reason}。依据：{url}",
    "halt_none": "本次未排除停市占位行",
})
_TEXT["ja_JP"].update({
    "halt_label": "確認済みの2020-10-01東証終日売買停止による空の相場行を除外",
    "halt_summary": "東証売買停止の除外: {status}",
    "halt_reason": "相場データ配信システム障害により東証の全銘柄で売買を停止",
    "halt_excluded": "{date} の {rows} 行を除外。{reason}。根拠: {url}",
    "halt_none": "今回、売買停止のプレースホルダー行は除外されませんでした",
})
_TEXT["en_US"].update({
    "halt_label": "Exclude verified empty rows for the 2020-10-01 all-day TSE halt",
    "halt_summary": "TSE halt exclusion: {status}",
    "halt_reason": "a market-data distribution system failure halted all TSE listed symbols",
    "halt_excluded": "Excluded {rows} rows on {date}: {reason}. Source: {url}",
    "halt_none": "No halt placeholder rows were excluded in this selection",
})


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _FreezeTask(QRunnable):
    def __init__(self, source_path, codes, start_date, end_date, price_basis, duplicate_policy,
                 known_halt_policy, output_dir):
        super().__init__()
        self.source_path = str(source_path)
        self.codes = tuple(codes)
        self.start_date, self.end_date = str(start_date), str(end_date)
        self.price_basis, self.duplicate_policy, self.output_dir = str(price_basis), str(duplicate_policy), Path(output_dir)
        self.known_halt_policy = str(known_halt_policy)
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            from .local_cache import load_research_bars
            selected = load_research_bars(self.source_path, codes=self.codes,
                start_date=self.start_date, end_date=self.end_date, price_basis=self.price_basis,
                duplicate_policy=self.duplicate_policy, known_halt_policy=self.known_halt_policy)
            factors = selected.bars.get("adjustment_factor")
            if factors is None:
                factor_reason = "adjustment_factor is missing"
            elif factors.isna().any():
                factor_reason = "adjustment_factor has missing values"
            elif not (factors.astype(float) == 1.0).all():
                factor_reason = "corporate-action model does not support non-1.0 split factors"
            else:
                factor_reason = ""
            manifest_path = selected.freeze(self.output_dir)
            verified = load_research_bars(manifest_path, codes=self.codes,
                start_date=self.start_date, end_date=self.end_date, price_basis=self.price_basis,
                duplicate_policy=self.duplicate_policy, known_halt_policy=self.known_halt_policy)
            if (verified.selected_data_sha256 != selected.selected_data_sha256
                    or verified.source["details"].get("pinned_identity_sha256") != selected.identity_sha256):
                raise ValueError("Frozen local-input identity did not round-trip exactly")
            per_code = selected.coverage["symbols"]
            self.signals.finished.emit({
                "manifest_path": str(manifest_path), "source": selected.source,
                "selection": selected.selection, "coverage": selected.coverage,
                "source_sha256": selected.source["source_sha256"],
                "selected_data_sha256": selected.selected_data_sha256,
                "identity_sha256": selected.identity_sha256,
                "native_backtest_compatible": not factor_reason,
                "native_backtest_reason": factor_reason,
                "first_date": min(item["first_observed_date"] for item in per_code),
                "last_date": max(item["last_observed_date"] for item in per_code),
                "requested_start": selected.coverage["requested_start"],
                "requested_end": selected.coverage["requested_end"],
                "rows": len(selected.bars),
                "duplicate_policy": selected.selection["duplicate_policy"],
                "duplicate_rows_removed": selected.coverage["duplicate_rows_removed"],
                "rows_before_dedup": selected.coverage["rows_before_dedup"],
                "verified_halt_exclusion": selected.coverage["verified_halt_exclusion"],
            })
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class LocalCachePanel(QGroupBox):
    input_ready = Signal(str, object)
    input_invalidated = Signal()

    def __init__(self, workspace: str | Path, language: str = "zh_CN", parent: QWidget | None = None):
        super().__init__(parent)
        self.workspace = Path(workspace).resolve()
        self.language = language if language in _TEXT else "zh_CN"
        self._task: _FreezeTask | None = None
        self._pool = QThreadPool(self); self._pool.setMaxThreadCount(1)
        self._last_result: dict | None = None
        self._status_error = ""
        root = QVBoxLayout(self)
        self.notice = QLabel(); self.notice.setWordWrap(True); root.addWidget(self.notice)
        self.source_path = QLineEdit(); self.source_path.setReadOnly(True)
        self.browse_button = QPushButton(); self.browse_button.clicked.connect(self._browse)
        source_row = QWidget(); source_layout = QHBoxLayout(source_row); source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(self.source_path, 1); source_layout.addWidget(self.browse_button); root.addWidget(source_row)
        self.codes = QLineEdit("7203")
        self.start_date = QDateEdit(QDate.currentDate().addYears(-1)); self.start_date.setCalendarPopup(True)
        self.end_date = QDateEdit(QDate.currentDate()); self.end_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd"); self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.price_basis = QComboBox(); self.price_basis.addItem("raw", "raw"); self.price_basis.addItem("adjusted", "adjusted")
        self.duplicate_policy = QComboBox()
        self.duplicate_policy.addItem("reject", "reject")
        self.duplicate_policy.addItem("drop_identical", "drop_identical")
        self.known_halt_exclusion = QCheckBox()
        self.codes.textChanged.connect(self._selection_edited)
        self.start_date.dateChanged.connect(self._selection_edited)
        self.end_date.dateChanged.connect(self._selection_edited)
        self.price_basis.currentIndexChanged.connect(self._selection_edited)
        self.duplicate_policy.currentIndexChanged.connect(self._selection_edited)
        self.known_halt_exclusion.toggled.connect(self._selection_edited)
        form = QFormLayout()
        self.codes_label = QLabel(); self.start_label = QLabel(); self.end_label = QLabel(); self.basis_label = QLabel(); self.duplicates_label = QLabel()
        form.addRow(self.codes_label, self.codes)
        form.addRow(self.start_label, self.start_date); form.addRow(self.end_label, self.end_date)
        form.addRow(self.basis_label, self.price_basis)
        form.addRow(self.duplicates_label, self.duplicate_policy)
        root.addLayout(form)
        root.addWidget(self.known_halt_exclusion)
        self.run_button = QPushButton(); self.run_button.clicked.connect(self.start_freeze); root.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.status = QLabel(); self.status.setWordWrap(True); root.addWidget(self.status)
        self.details_button = QToolButton(); self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_details); root.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.details = QLabel(); self.details.setWordWrap(True); self.details.hide(); root.addWidget(self.details)
        self.set_language(self.language)

    def _t(self, key: str) -> str:
        return _TEXT[self.language][key]

    @Slot(bool)
    def _toggle_details(self, expanded: bool) -> None:
        self.details.setVisible(expanded)

    def set_language(self, language: str) -> None:
        self.language = language if language in _TEXT else "zh_CN"
        self.setTitle(self._t("title")); self.notice.setText(self._t("notice"))
        self.browse_button.setText(self._t("browse")); self.codes_label.setText(self._t("codes"))
        self.start_label.setText(self._t("start")); self.end_label.setText(self._t("end"))
        self.basis_label.setText(self._t("basis")); self.price_basis.setItemText(0, self._t("raw"))
        self.price_basis.setItemText(1, self._t("adjusted")); self.run_button.setText(self._t("run"))
        self.duplicates_label.setText(self._t("duplicates"))
        self.duplicate_policy.setItemText(0, self._t("reject_duplicates"))
        self.duplicate_policy.setItemText(1, self._t("drop_identical"))
        self.known_halt_exclusion.setText(self._t("halt_label"))
        self.details_button.setText(self._t("details"))
        if self._task is None:
            self._render_status()

    def _render_status(self) -> None:
        if self._task is not None:
            self.status.setText(self._t("running")); return
        if self._last_result is None:
            self.status.setText(f"{self._t('failed')}: {self._status_error}" if self._status_error else self._t("ready"))
            self.details.clear(); return
        result = self._last_result
        summary = self._t("coverage").format(requested_start=result["requested_start"],
            requested_end=result["requested_end"], rows=result["rows"], first=result["first_date"],
            last=result["last_date"], kind=result["source"]["kind"], basis=result["selection"]["price_basis"])
        hashes = self._t("hash").format(source=result["source_sha256"],
            selected=result["selected_data_sha256"], identity=result["identity_sha256"])
        compatibility = (self._t("backtest_ok") if result["native_backtest_compatible"] else
                         self._t("backtest_blocked").format(reason=result["native_backtest_reason"]))
        duplicate_summary = self._t("duplicate_count").format(
            policy=self._t("reject_duplicates" if result["duplicate_policy"] == "reject"
                           else "drop_identical"),
            input_rows=result["rows_before_dedup"], retained_rows=result["rows"],
            removed=result["duplicate_rows_removed"])
        halt = result.get("verified_halt_exclusion")
        halt_status = (self._t("halt_excluded").format(rows=halt["rows"], date=halt["date"],
                        reason=self._t("halt_reason"), url=halt["source_url"]) if halt else self._t("halt_none"))
        halt_summary = self._t("halt_summary").format(status=halt_status)
        self.status.setText(f"{self._t('complete')} · {summary}\n{duplicate_summary}\n{halt_summary}\n{compatibility}")
        self.details.setText(f"{hashes}\n{self._t('pit')}\n{self._t('frozen').format(path=result['manifest_path'])}")

    def set_source_path(self, path: str | Path) -> None:
        changed = self.source_path.text() != str(path)
        self.source_path.setText(str(path))
        if changed: self._invalidate_selection()

    @Slot()
    def _selection_edited(self, *_args) -> None:
        self._invalidate_selection()

    def _invalidate_selection(self) -> None:
        self._last_result = None; self._status_error = ""
        self._render_status()
        self.input_invalidated.emit()

    def set_selection(self, codes, start_date: str, end_date: str, price_basis: str = "raw",
                      duplicate_policy: str = "reject", known_halt_policy: str = "reject") -> None:
        self.codes.setText(",".join(str(code) for code in codes))
        self.start_date.setDate(QDate.fromString(str(start_date), "yyyy-MM-dd"))
        self.end_date.setDate(QDate.fromString(str(end_date), "yyyy-MM-dd"))
        index = self.price_basis.findData(price_basis)
        if index < 0:
            raise ValueError("price_basis must be raw or adjusted")
        self.price_basis.setCurrentIndex(index)
        duplicate_index = self.duplicate_policy.findData(duplicate_policy)
        if duplicate_index < 0:
            raise ValueError("duplicate_policy must be reject or drop_identical")
        self.duplicate_policy.setCurrentIndex(duplicate_index)
        if known_halt_policy not in {"reject", "exclude_verified_tse_halt_20201001"}:
            raise ValueError("unsupported known-halt exclusion policy")
        self.known_halt_exclusion.setChecked(known_halt_policy != "reject")

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self._t("source"), str(self.workspace), self._t("filter"))
        if path:
            self.set_source_path(path)

    def start_freeze(self) -> bool:
        if self._task is not None:
            return False
        source = Path(self.source_path.text()).expanduser()
        if not source.is_file():
            self.status.setText(self._t("no_source")); return False
        codes = tuple(item.strip() for item in self.codes.text().replace("，", ",").split(",") if item.strip())
        if not codes:
            self.status.setText(self._t("bad_codes")); return False
        start, end = self.start_date.date().toString("yyyy-MM-dd"), self.end_date.date().toString("yyyy-MM-dd")
        run_root = self.workspace / "local_market_inputs" / f"input-{uuid.uuid4().hex}"
        task = _FreezeTask(source, codes, start, end, self.price_basis.currentData(),
                           self.duplicate_policy.currentData(),
                           ("exclude_verified_tse_halt_20201001" if self.known_halt_exclusion.isChecked() else "reject"),
                           run_root)
        task.signals.finished.connect(self._finished); task.signals.failed.connect(self._failed)
        self._status_error = ""; self._task = task
        self._set_busy(True); self._render_status(); self._pool.start(task)
        return True

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.source_path, self.browse_button, self.codes, self.start_date,
                       self.end_date, self.price_basis, self.duplicate_policy,
                       self.known_halt_exclusion, self.run_button):
            widget.setEnabled(not busy)

    @Slot(object)
    def _finished(self, result: dict) -> None:
        self._last_result = result; self._task = None; self._set_busy(False); self._render_status()
        self.input_ready.emit(result["manifest_path"], result)

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._task = None; self._last_result = None; self._status_error = str(message); self._set_busy(False)
        self.input_invalidated.emit(); self._render_status()


__all__ = ["LocalCachePanel"]
