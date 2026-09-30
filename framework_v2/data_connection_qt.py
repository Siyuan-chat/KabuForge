"""User-triggered J-Quants connection and local download panel."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import threading

from PySide6.QtCore import QObject, QThread, QDate, Qt, Signal, Slot
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QDateEdit)

from . import data_connection as backend


_TEXT = {
    "zh_CN": {
        "title": "J-Quants 数据连接", "key": "API 密钥", "remember": "保存到 Windows 凭据管理器",
        "test": "测试连接", "show": "显示密钥", "forget": "删除已存密钥", "codes": "证券代码（逗号分隔）", "start": "开始日期", "end": "结束日期",
        "download": "下载日线", "cancel": "取消", "idle": "就绪。连接和下载只在点击按钮后执行。",
        "testing": "正在测试连接…", "connected": "连接成功", "downloading": "正在下载…",
        "complete": "下载完成：{path}", "cancelled": "已取消；再次下载可续传。",
        "failed": "操作失败：{error}", "progress": "{code} 第 {page} 页；完成 {done}/{total} 个代码",
        "auth_error": "密钥无效或当前套餐无权访问；请核对 J-Quants 控制台。", "rate_error": "请求过于频繁；请稍后重试，已下载页面可续传。",
        "network_error": "网络请求失败；请检查连接后重试。", "empty_error": "所选代码和日期没有日线数据；请检查交易日或套餐覆盖范围。",
        "busy_error": "同一下载正在另一个窗口运行。", "key_error": "请输入 API 密钥。", "range_error": "开始日期不能晚于结束日期。",
        "codes_error": "请输入至少一个 4 或 5 位证券代码。", "forgot": "已删除 Windows 凭据管理器中的密钥。",
        "disclaimer": "当前 API 日线仅供本地研究；未验证历史可用时间，不可用于严格 PIT 快照。",
    },
    "ja_JP": {
        "title": "J-Quants データ接続", "key": "API キー", "remember": "Windows 資格情報に保存",
        "test": "接続テスト", "show": "キーを表示", "forget": "保存したキーを削除", "codes": "銘柄コード（カンマ区切り）", "start": "開始日", "end": "終了日",
        "download": "日足を取得", "cancel": "キャンセル", "idle": "準備完了。接続と取得はボタンを押した時だけ実行します。",
        "testing": "接続を確認中…", "connected": "接続成功", "downloading": "取得中…",
        "complete": "取得完了：{path}", "cancelled": "中止しました。再実行で続きから取得できます。",
        "failed": "失敗：{error}", "progress": "{code} {page} ページ；{done}/{total} 銘柄完了",
        "auth_error": "キーが無効か、契約プランにアクセス権がありません。J-Quants ダッシュボードを確認してください。", "rate_error": "リクエスト制限です。後ほど再試行できます。取得済みページは再利用されます。",
        "network_error": "通信に失敗しました。接続を確認して再試行してください。", "empty_error": "指定した銘柄と期間に日足がありません。営業日とプランの対象期間を確認してください。",
        "busy_error": "同じ取得処理が別ウィンドウで実行中です。", "key_error": "API キーを入力してください。", "range_error": "開始日は終了日以前にしてください。",
        "codes_error": "4 または 5 桁の銘柄コードを入力してください。", "forgot": "Windows 資格情報からキーを削除しました。",
        "disclaimer": "現在の API 日足はローカル研究用です。過去の利用可能時刻は未検証で、厳格な PIT スナップショットには使えません。",
    },
    "en_US": {
        "title": "J-Quants data connection", "key": "API key", "remember": "Save in Windows Credential Manager",
        "test": "Test connection", "show": "Show key", "forget": "Delete saved key", "codes": "Security codes (comma separated)", "start": "Start date", "end": "End date",
        "download": "Download daily bars", "cancel": "Cancel", "idle": "Ready. Connection and download run only when you click a button.",
        "testing": "Testing connection…", "connected": "Connection successful", "downloading": "Downloading…",
        "complete": "Download complete: {path}", "cancelled": "Cancelled; run again to resume.",
        "failed": "Operation failed: {error}", "progress": "{code} page {page}; {done}/{total} codes done",
        "auth_error": "The key is invalid or your plan cannot access this data. Check the J-Quants dashboard.", "rate_error": "Rate limit reached. Try again later; downloaded pages will resume.",
        "network_error": "Network request failed. Check your connection and try again.", "empty_error": "No daily bars for these codes and dates. Check trading days and plan coverage.",
        "busy_error": "The same download is running in another window.", "key_error": "Enter an API key.", "range_error": "Start date must not follow end date.",
        "codes_error": "Enter one or more 4- or 5-digit security codes.", "forgot": "Saved key removed from Windows Credential Manager.",
        "disclaimer": "Current API bars are for local research. Historical availability is unverified; do not use for strict PIT snapshots.",
    },
}


class _Worker(QObject):
    progress = Signal(dict)
    finished = Signal(str, object)

    def __init__(self, mode: str, workspace: Path, api_key: str, codes: list[str], start: str, end: str):
        super().__init__()
        self.mode, self.workspace, self.api_key = mode, workspace, api_key
        self.codes, self.start, self.end = codes, start, end
        self.cancel_event = threading.Event()

    @Slot()
    def run(self):
        try:
            if self.mode == "test":
                backend.test_connection(self.api_key)
                self.finished.emit("connected", None)
            else:
                result = backend.download_bars(self.workspace, self.api_key, self.codes, self.start, self.end,
                                               cancel_event=self.cancel_event, progress=self.progress.emit)
                self.finished.emit("downloaded", str(result))
        except backend.DownloadCancelled:
            self.finished.emit("cancelled", None)
        except Exception as exc:
            # Backend errors never carry request headers or response bodies.
            self.finished.emit("failed", str(exc).replace(self.api_key, "***"))


class DataConnectionPanel(QWidget):
    """Embeddable panel. ``downloaded(str)`` fires for a completed manifest."""
    downloaded = Signal(str)

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def __init__(self, workspace, language="zh_CN", parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace).resolve()
        self.language = language if language in _TEXT else "zh_CN"
        self._thread = None
        self._worker = None
        self._status_key = "idle"
        self._status_args = {}
        outer = QVBoxLayout(self)
        self.title_label = QLabel()
        outer.addWidget(self.title_label)
        form = QFormLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setAccessibleName("J-Quants API key")
        self.remember = QCheckBox()
        self.key_label = QLabel()
        form.addRow(self.key_label, self.api_key)
        self.show_key = QCheckBox()
        form.addRow("", self.show_key)
        form.addRow("", self.remember)
        self.codes = QLineEdit()
        self.codes.setPlaceholderText("7203, 6758")
        self.codes_label = QLabel()
        form.addRow(self.codes_label, self.codes)
        self.start = QDateEdit()
        self.end = QDateEdit()
        for field in (self.start, self.end):
            field.setCalendarPopup(True)
            field.setDisplayFormat("yyyy-MM-dd")
        self.end.setDate(QDate.currentDate())
        self.start.setDate(QDate.currentDate().addYears(-1))
        self.start_label = QLabel()
        self.end_label = QLabel()
        form.addRow(self.start_label, self.start)
        form.addRow(self.end_label, self.end)
        outer.addLayout(form)
        self._form = form
        buttons = QHBoxLayout()
        self.test_button = QPushButton()
        self.forget_button = QPushButton()
        self.download_button = QPushButton()
        self.cancel_button = QPushButton()
        buttons.addWidget(self.test_button)
        buttons.addWidget(self.forget_button)
        buttons.addWidget(self.download_button)
        buttons.addWidget(self.cancel_button)
        outer.addLayout(buttons)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        self.disclaimer_label = QLabel()
        self.disclaimer_label.setWordWrap(True)
        outer.addWidget(self.disclaimer_label)
        self.test_button.clicked.connect(lambda: self._start("test"))
        self.forget_button.clicked.connect(self.forget_saved_key)
        self.show_key.toggled.connect(lambda checked: self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        self.download_button.clicked.connect(lambda: self._start("download"))
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        try:
            saved = backend.load_api_key()
            if saved:
                self.api_key.setText(saved)
                self.remember.setChecked(True)
        except OSError:
            pass
        self.set_language(self.language)

    def set_language(self, locale):
        self.language = locale if locale in _TEXT else "zh_CN"
        t = _TEXT[self.language]
        self.title_label.setText(t["title"])
        self.remember.setText(t["remember"])
        self.show_key.setText(t["show"])
        self.forget_button.setText(t["forget"])
        for label, name in ((self.key_label, "key"), (self.codes_label, "codes"),
                            (self.start_label, "start"), (self.end_label, "end")):
            label.setText(t[name])
        self.test_button.setText(t["test"])
        self.download_button.setText(t["download"])
        self.cancel_button.setText(t["cancel"])
        self.disclaimer_label.setText(t["disclaimer"])
        self.status_label.setText(t[self._status_key].format(**self._status_args))

    def _status(self, key, **kwargs):
        self._status_key, self._status_args = key, kwargs
        self.status_label.setText(_TEXT[self.language][key].format(**kwargs))

    def _friendly_error(self, error):
        key = ""
        if "HTTP 401" in error or "HTTP 403" in error:
            key = "auth_error"
        elif "HTTP 429" in error:
            key = "rate_error"
        elif "network request failed" in error:
            key = "network_error"
        elif "No daily bars returned" in error:
            key = "empty_error"
        elif "already running in another window" in error:
            key = "busy_error"
        elif "API key is required" in error:
            key = "key_error"
        elif "Start date must not follow" in error:
            key = "range_error"
        elif "security codes" in error:
            key = "codes_error"
        return _TEXT[self.language].get(key, error)

    def forget_saved_key(self):
        if self.busy:
            return
        try:
            backend.delete_api_key()
        except OSError as exc:
            self._status("failed", error=str(exc))
            return
        self.api_key.clear()
        self.remember.setChecked(False)
        self._status("forgot")

    def _start(self, mode):
        if self._thread is not None:
            return
        try:
            key = self.api_key.text().strip()
            if not key:
                raise ValueError("API key is required")
            codes = [part.strip() for part in re.split(r"[,，\s]+", self.codes.text()) if part.strip()]
            if mode == "download":
                backend._codes(codes)
                if self.start.date() > self.end.date():
                    raise ValueError("Start date must not follow end date")
            if self.remember.isChecked():
                backend.save_api_key(key)
        except (ValueError, OSError) as exc:
            self._status("failed", error=self._friendly_error(str(exc)))
            return
        self._worker = _Worker(mode, self.workspace, key, codes,
                               self.start.date().toString("yyyy-MM-dd"), self.end.date().toString("yyyy-MM-dd"))
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit, Qt.ConnectionType.DirectConnection)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_thread)
        self.test_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.cancel_button.setEnabled(mode == "download")
        self._status("testing" if mode == "test" else "downloading")
        self._thread.start()

    @Slot(dict)
    def _on_progress(self, value):
        self._status("progress", code=value["code"], page=value["page"],
                     done=value["completed_codes"], total=value["total_codes"])

    @Slot(str, object)
    def _on_finished(self, outcome, value):
        if outcome == "downloaded":
            self._status("complete", path=value)
            self.downloaded.emit(value)
        elif outcome == "failed":
            self._status("failed", error=self._friendly_error(value))
        else:
            self._status(outcome)
        self.cancel_button.setEnabled(False)

    @Slot()
    def _clear_thread(self):
        self._thread = None
        self._worker = None
        self.test_button.setEnabled(True)
        self.download_button.setEnabled(True)

    def cancel(self):
        if self._worker is not None:
            self._worker.cancel_event.set()
            self.cancel_button.setEnabled(False)

    def closeEvent(self, event):
        self.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(50000)
        super().closeEvent(event)
