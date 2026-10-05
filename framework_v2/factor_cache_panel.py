"""Explicit GUI control for the isolated history factor cache."""
from __future__ import annotations
import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QVBoxLayout


class FactorCachePanel(QGroupBox):
    enabled_changed = Signal(bool)

    _TEXT = {
        "zh_CN": {
            "title": "历史因子缓存",
            "toggle": "启用本机复用缓存（默认关闭）",
            "scope": "仅用于因子策略历史回测；Native 价格动量/MA 研究与指标面板不使用此缓存。",
            "disabled": "关闭：不会创建或读取缓存文件。",
            "ready": "已启用；缓存固定保存在当前工作区的 cache/history-factors.sqlite。",
            "running": "任务运行中，缓存选项已锁定。",
            "summary": "缓存结果：命中 {hits} · 未命中 {misses} · 写入 {writes} · 损坏 {corrupt} · 命名空间 {identity}",
            "failure": "缓存被拒绝，未回退重算：损坏 {corrupt} · 详情见 {path}",
        },
        "ja_JP": {
            "title": "履歴ファクターキャッシュ",
            "toggle": "ローカル再利用キャッシュを有効化（既定はオフ）",
            "scope": "ファクター戦略の履歴バックテスト専用です。Native 価格モメンタム/MA 研究と指標パネルでは使用しません。",
            "disabled": "オフ：キャッシュファイルを作成・読み込みしません。",
            "ready": "有効です。現在のワークスペース内 cache/history-factors.sqlite に保存します。",
            "running": "処理中のため、キャッシュ設定をロックしています。",
            "summary": "キャッシュ結果：ヒット {hits} · ミス {misses} · 書込 {writes} · 破損 {corrupt} · 名前空間 {identity}",
            "failure": "キャッシュを拒否し再計算していません：破損 {corrupt} · 詳細：{path}",
        },
        "en_US": {
            "title": "History factor cache",
            "toggle": "Enable local reuse cache (off by default)",
            "scope": "Only for factor-strategy history backtests. Native price momentum/MA research and the indicator panel do not use this cache.",
            "disabled": "Off: no cache file is created or read.",
            "ready": "Enabled. Stored at cache/history-factors.sqlite inside this workspace.",
            "running": "Job running; cache selection is locked.",
            "summary": "Cache result: hits {hits} · misses {misses} · writes {writes} · corrupt {corrupt} · namespace {identity}",
            "failure": "Cache rejected; no recompute fallback: corrupt {corrupt} · details: {path}",
        },
    }

    def __init__(self, workspace, language="zh_CN", parent=None):
        super().__init__(parent)
        self.workspace = str(workspace)
        self.language = language if language in self._TEXT else "zh_CN"
        self._busy = False
        self._summary = None
        self._failure_path = None
        layout = QVBoxLayout(self)
        self.toggle = QCheckBox(self)
        self.scope = QLabel(self)
        self.scope.setWordWrap(True)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.toggle)
        layout.addWidget(self.scope)
        layout.addWidget(self.status)
        self.toggle.toggled.connect(self._on_toggled)
        self.set_language(self.language)

    def is_enabled(self):
        return self.toggle.isChecked()

    def _on_toggled(self, enabled):
        self._summary = None
        self._failure_path = None
        self._render_status()
        self.enabled_changed.emit(bool(enabled))

    def selection(self, *, enabled=None):
        return {"schema": "kabuforge.factor-cache-selection.v1",
                "enabled": self.is_enabled() if enabled is None else bool(enabled),
                "workspace_path": self.workspace}

    def set_busy(self, busy):
        self._busy = bool(busy)
        self.toggle.setEnabled(not self._busy)
        self._render_status()

    def show_summary(self, value):
        self._summary = dict(value or {})
        self._failure_path = None
        self._render_status()

    def clear_summary(self):
        self._summary = None
        self._failure_path = None
        self._render_status()

    def show_failure(self, path):
        self._summary = None
        self._failure_path = str(path)
        self._render_status()

    def _render_status(self):
        text = self._TEXT[self.language]
        if self._busy:
            self.status.setText(text["running"])
        elif self._failure_path:
            try:
                receipt = json.loads(Path(self._failure_path).read_text(encoding="utf-8"))
                count = (receipt.get("stats") or {}).get("corrupt", "?")
            except (OSError, ValueError, TypeError):
                count = "?"
            self.status.setText(text["failure"].format(corrupt=count, path=self._failure_path))
        elif self._summary and self._summary.get("enabled") is False:
            self.status.setText(text["disabled"])
        elif self._summary:
            stats = self._summary.get("stats") or {}
            identity = str(self._summary.get("namespace_identity") or "—")[:16]
            self.status.setText(text["summary"].format(
                hits=stats.get("hits", 0), misses=stats.get("misses", 0),
                writes=stats.get("writes", 0), corrupt=stats.get("corrupt", 0),
                identity=identity))
        else:
            self.status.setText(text["ready"] if self.is_enabled() else text["disabled"])

    def set_language(self, language):
        self.language = language if language in self._TEXT else "zh_CN"
        text = self._TEXT[self.language]
        self.setTitle(text["title"])
        self.toggle.setText(text["toggle"])
        self.scope.setText(text["scope"])
        self.toggle.setAccessibleName(text["toggle"])
        self._render_status()
