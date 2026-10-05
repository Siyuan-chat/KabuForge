"""Compact, truthful integration status panel for the product GUI."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .integrations import IntegrationStatus, inspect_integrations


class IntegrationsPanel(QGroupBox):
    def __init__(self, language: str = "zh_CN", parent: QWidget | None = None):
        super().__init__(parent)
        self.language = language
        self.rows: dict[str, tuple[QLabel, QLabel, QLabel, QLabel]] = {}
        self._layout = QVBoxLayout(self)
        self.explainer = QLabel()
        self.explainer.setWordWrap(True)
        self._layout.addWidget(self.explainer)
        self._refresh_button = QPushButton()
        self._refresh_button.clicked.connect(self.refresh)
        self._layout.addWidget(self._refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._set_static_text()
        self.refresh()

    def _text(self, zh: str, ja: str, en: str) -> str:
        return {"zh_CN": zh, "ja_JP": ja, "en_US": en}.get(self.language, zh)

    def _set_static_text(self) -> None:
        self.setTitle(self._text("集成与运行时", "連携とランタイム", "Integrations and runtimes"))
        self.explainer.setText(self._text(
            "这里只读检查工作流接入、包发现和固定运行时收据；启动时不导入重型可选库、不连接服务、不读取凭证。券商纯本地映射也不读凭证、不联网；仅券商页的独立只读检查按钮会解析既有环境变量引用，并向固定 localhost 对现金、持仓、订单各发送一个 GET。该功能未在真实终端验证；提交与撤销禁用。包发现或收据通过不代表本次计算成功；最近任务回执不会自动扫描。",
            "ここではワークフロー接続、パッケージ検出、固定ランタイムレシートのみを確認します。起動時に重い任意ライブラリをimportせず、接続や認証情報読取もしません。証券会社のローカルマッピングも資格情報を読まず通信しません。証券会社画面の独立した読取専用ボタンを押した場合のみ、既存の環境変数参照を解決し、固定 localhost に現金・保有・注文を各1回GETします。実端末での動作は未検証で、発注・取消は無効です。検出・レシート合格は今回の計算成功を意味せず、最新の実行記録も自動走査しません。",
            "This view checks workflow integration, package discovery, and fixed runtime receipts only. Startup does not import heavy optional libraries, connect to services, or read credentials. Broker mapping is also local-only and reads no credentials. Only the separate read-only button on the broker page resolves an existing environment-variable reference and sends one GET each for cash, positions, and orders to the fixed localhost endpoint. This has not been validated against a real terminal; submission and cancellation are disabled. Discovery or a verified receipt does not mean a calculation succeeded; recent task receipts are not scanned."))
        self._refresh_button.setText(self._text("刷新本地元数据", "ローカルメタデータを更新", "Refresh local metadata"))

    def set_language(self, language: str) -> None:
        self.language = language
        self._set_static_text()
        self.refresh()

    def refresh(self, statuses: tuple[IntegrationStatus, ...] | None = None) -> None:
        current = statuses if statuses is not None else inspect_integrations()
        for status in current:
            row = self.rows.get(status.spec.id)
            if row is None:
                container = QWidget(self)
                layout = QHBoxLayout(container)
                layout.setContentsMargins(0, 2, 0, 2)
                name, lifecycle, dependency, details = QLabel(), QLabel(), QLabel(), QLabel()
                name.setMinimumWidth(112)
                lifecycle.setMinimumWidth(130)
                dependency.setMinimumWidth(250)
                details.setWordWrap(True)
                layout.addWidget(name)
                layout.addWidget(lifecycle)
                layout.addWidget(dependency)
                layout.addWidget(details, 1)
                self._layout.insertWidget(self._layout.count() - 1, container)
                row = (name, lifecycle, dependency, details)
                self.rows[status.spec.id] = row
            self._render(status, row)

    def _package_state(self, status: IntegrationStatus) -> str:
        if not status.packages:
            return self._text("无可选包依赖", "任意パッケージ依存なし", "No optional package")
        if status.package_discoverable:
            return self._text("当前进程可发现；import 未执行", "現在のプロセスで検出；import未実行", "Discovered in this process; import pending")
        return self._text("当前进程未发现所需可选包", "現在のプロセスで必要な任意パッケージ未検出", "Required optional packages not discovered in this process")

    def _runtime_state(self, status: IntegrationStatus) -> str:
        if status.runtime_launchable:
            return self._text("解释器与依赖元数据可用；本次工作流尚未运行", "実行環境と依存関係メタデータを確認；今回の計算は未実行", "Interpreter and dependency metadata are available; this workflow has not run")
        reason = status.reason or "required dependencies are unavailable"
        return self._text("当前依赖不可用：", "必要な依存関係を利用できません：", "Required dependencies unavailable: ") + reason

    def _render(self, status: IntegrationStatus, row: tuple[QLabel, QLabel, QLabel, QLabel]) -> None:
        name, lifecycle, dependency, details = row
        spec = status.spec
        name.setText(spec.name)
        if spec.workflow_implemented:
            lifecycle.setText(self._text("工作流已实现", "ワークフロー実装済み", "Workflow implemented"))
        elif status.lifecycle == "blocked":
            lifecycle.setText(self._text("依赖不可用", "依存関係を利用できません", "Dependencies unavailable"))
        elif spec.lifecycle == "experimental":
            lifecycle.setText(self._text("实验阶段", "実験段階", "Experimental"))
        else:
            lifecycle.setText(self._text("规划中", "計画中", "Planned"))
        dependency.setText(self._package_state(status) + " · " + self._runtime_state(status))
        detail = spec.description_for(self.language)
        if status.packages:
            versions = ", ".join(
                f"{item.get('name', 'package')} {item.get('version') or 'unknown'}"
                for item in status.packages
            )
            detail += " · " + self._text("依赖元数据：", "依存関係メタデータ：", "Dependency metadata: ") + versions
        capabilities = spec.capabilities
        if capabilities:
            detail += " · " + " / ".join(capabilities)
        details.setText(detail)
        details.setToolTip(status.reason or "")
        # Preserve the old styling signal/API used by existing GUI code.
        lifecycle.setProperty("available", status.workflow_ready)
        lifecycle.style().unpolish(lifecycle)
        lifecycle.style().polish(lifecycle)
