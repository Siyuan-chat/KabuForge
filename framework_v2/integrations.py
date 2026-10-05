"""Public integration inventory with workflow and dependency state separated."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .research_runtime import resolve_research_runtime


@dataclass(frozen=True)
class IntegrationSpec:
    id: str
    name: str
    description: str
    operation: str
    lifecycle: str
    workflow_implemented: bool
    choices: tuple[tuple[str, object], ...] = ()
    capabilities: tuple[str, ...] = ()
    localized_names: tuple[tuple[str, str], ...] = ()
    localized_descriptions: tuple[tuple[str, str], ...] = ()

    def name_for(self, language: str) -> str:
        return dict(self.localized_names).get(language, self.name)

    def description_for(self, language: str) -> str:
        return dict(self.localized_descriptions).get(language, self.description)


@dataclass(frozen=True)
class IntegrationStatus:
    spec: IntegrationSpec
    dependencies_available: bool
    runtime_launchable: bool | None
    package_discoverable: bool | None
    packages: tuple[dict[str, object], ...]
    import_status: str
    reason: str | None

    @property
    def lifecycle(self) -> str:
        if not self.spec.workflow_implemented or self.spec.lifecycle == "planned":
            return "planned"
        return self.spec.lifecycle if self.dependencies_available else "blocked"

    @property
    def workflow_ready(self) -> bool:
        """A discoverable package alone never makes a workflow ready."""
        return self.spec.workflow_implemented and self.dependencies_available


def _spec(id_, name, description, operation, lifecycle, implemented, *,
          capabilities=(), localized_names=(), localized_descriptions=(), choices=()):
    return IntegrationSpec(id_, name, description, operation, lifecycle, implemented,
        tuple(choices), tuple(capabilities), tuple(localized_names), tuple(localized_descriptions))


DEFAULT_INTEGRATIONS = (
    _spec("jquants", "J-Quants", "Explicit J-Quants v2 download and completed-manifest import; historical visibility is unverified.",
        "jquants-download", "available", True, capabilities=("explicit network action", "resumable daily bars", "historical visibility unverified"),
        localized_names=(("zh_CN", "J-Quants 数据下载"), ("ja_JP", "J-Quants データ取得")),
        localized_descriptions=(("zh_CN", "显式执行 J-Quants v2 下载并导入完成清单；历史可见性未认证。"),
            ("ja_JP", "明示操作で J-Quants v2 を取得し、完了マニフェストを読込みます。履歴の可視時点は未認証です。"))),
    _spec("native", "Native research", "The existing public daily-bar momentum research flow; research-only and historical visibility unverified.",
        "native", "available", True, capabilities=("daily-bar price momentum", "next-open research execution", "PIT unverified"),
        localized_names=(("zh_CN", "Native 研究核心"), ("ja_JP", "Native 研究コア")),
        localized_descriptions=(("zh_CN", "现有公版日线价格动量研究流程；仅研究用途，历史可见性未认证。"),
            ("ja_JP", "既存の公開日足価格モメンタム研究です。研究専用で履歴の可視時点は未認証です。"))),
    _spec("local-cache", "Local market cache", "Select and pin an explicit local CSV, Parquet, or completed manifest. No source tree scanning or availability timestamps are inferred.",
        "local-cache", "available", True, capabilities=("explicit file selection", "source hashes and coverage", "historical visibility remains unverified"),
        localized_names=(("zh_CN", "本地行情缓存"), ("ja_JP", "ローカル市場キャッシュ")),
        localized_descriptions=(("zh_CN", "显式选择并冻结本地 CSV、Parquet 或完成清单；不扫描父目录，也不推断可用时间。"),
            ("ja_JP", "ローカルCSV、Parquet、完了済みマニフェストを明示選択して固定します。親ディレクトリ走査や可視時刻の推測はしません。"))),
    _spec("talib", "TA-Lib indicators", "The GUI can calculate and display SMA, RSI, MACD, and ATR through the selected TA-Lib worker. Dependency discovery does not imply an import or run succeeded.",
        "indicator-talib", "available", True, capabilities=("isolated TA-Lib worker", "SMA/RSI/MACD/ATR", "per-run result identity"),
        localized_names=(("zh_CN", "TA-Lib 指标"), ("ja_JP", "TA-Lib 指標")),
        localized_descriptions=(("zh_CN", "GUI 通过隔离 worker 计算并显示 SMA、RSI、MACD 和 ATR；依赖发现不代表导入或运行成功。"),
            ("ja_JP", "GUIは分離workerでSMA、RSI、MACD、ATRを計算・表示します。依存関係の検出はimportや実行成功を意味しません。"))),
    _spec("pandas-ta", "pandas-ta indicators", "The GUI can calculate and display selected pandas-ta indicators in an isolated worker with TA-Lib auto-selection disabled.",
        "indicator-pandas-ta", "available", True, capabilities=("isolated pandas-ta worker", "TA-Lib auto-selection disabled", "SMA/RSI/MACD/ATR"),
        localized_names=(("zh_CN", "pandas-ta 指标"), ("ja_JP", "pandas-ta 指標")),
        localized_descriptions=(("zh_CN", "GUI 在隔离 worker 中调用 pandas-ta，并关闭其自动选择 TA-Lib 的行为。"),
            ("ja_JP", "GUIは分離workerでpandas-taを呼び出し、TA-Libの自動選択を無効にします。"))),
    _spec("analytics", "jQuantStats report", "The GUI adapts actual strategy NAV returns into an offline local report and interactive charts. Missing optional dependencies block chart generation explicitly.",
        "analytics", "available", True, capabilities=("actual NAV return input", "paired benchmark statistics", "offline local HTML"),
        localized_names=(("zh_CN", "jQuantStats 分析报告"), ("ja_JP", "jQuantStats 分析レポート")),
        localized_descriptions=(("zh_CN", "GUI 将实际策略 NAV 收益适配为本地离线报告和交互图；缺少可选依赖时明确阻止生成。"),
            ("ja_JP", "GUIは実際の戦略NAVリターンをローカルのオフラインレポートとチャートに適用します。依存関係不足時は生成を明確に停止します。"))),
    _spec("lightgbm", "LightGBM", "The GUI trains the selected fixed LightGBM time-split model in an isolated worker and can pass feature-only predictions to research replay. No random split or test-period tuning is performed.",
        "model-training", "available", True, choices=(("model_names", ("lightgbm",)),), capabilities=("isolated selected-model worker", "fixed chronological split", "feature-only strategy input"),
        localized_names=(("zh_CN", "LightGBM 时序模型"), ("ja_JP", "LightGBM 時系列モデル")),
        localized_descriptions=(("zh_CN", "GUI 在隔离 worker 中训练固定时序切分的 LightGBM，并可将仅特征预测用于研究回放；不随机切分或用测试期调参。"),
            ("ja_JP", "GUIは分離workerで固定時系列分割のLightGBMを学習し、特徴量のみの予測を研究リプレイに渡せます。ランダム分割やテスト期間調整はしません。"))),
    _spec("catboost", "CatBoost", "The GUI trains the selected fixed CatBoost time-split model in an isolated worker and can pass feature-only predictions to research replay. No random split or test-period tuning is performed.",
        "model-training", "available", True, choices=(("model_names", ("catboost",)),), capabilities=("isolated selected-model worker", "fixed chronological split", "feature-only strategy input"),
        localized_names=(("zh_CN", "CatBoost 时序模型"), ("ja_JP", "CatBoost 時系列モデル")),
        localized_descriptions=(("zh_CN", "GUI 在隔离 worker 中训练固定时序切分的 CatBoost，并可将仅特征预测用于研究回放；不随机切分或用测试期调参。"),
            ("ja_JP", "GUIは分離workerで固定時系列分割のCatBoostを学習し、特徴量のみの予測を研究リプレイに渡せます。ランダム分割やテスト期間調整はしません。"))),
    _spec("vectorbt", "VectorBT", "The GUI compares a frozen fixed-quantity schedule through the isolated VectorBT portfolio engine. This is an execution comparison, not an independently optimized strategy.",
        "engine-comparison", "available", True, choices=(("backends", ("vectorbt",)),), capabilities=("isolated VectorBT worker", "fixed order schedule", "native comparison"),
        localized_names=(("zh_CN", "VectorBT 执行引擎"), ("ja_JP", "VectorBT 実行エンジン")),
        localized_descriptions=(("zh_CN", "GUI 使用隔离 VectorBT 组合引擎回放固定数量订单计划；这是执行对照，不是独立优化策略。"),
            ("ja_JP", "GUIは分離VectorBTポートフォリオで固定数量の注文計画を再生します。独立して最適化した戦略ではなく実行比較です。"))),
    _spec("backtrader", "Backtrader", "The GUI compares the frozen schedule through the isolated next-bar Backtrader engine. Engine differences remain visible and are not hidden by selecting a winner.",
        "engine-comparison", "available", True, choices=(("backends", ("backtrader",)),), capabilities=("isolated Backtrader worker", "next-bar execution", "native comparison"),
        localized_names=(("zh_CN", "Backtrader 执行引擎"), ("ja_JP", "Backtrader 実行エンジン")),
        localized_descriptions=(("zh_CN", "GUI 在隔离 worker 中通过 Backtrader 下一根 bar 引擎对照冻结订单计划；保留引擎差异，不自动挑选赢家。"),
            ("ja_JP", "GUIは分離workerのBacktrader次足エンジンで固定注文計画を比較します。差異を表示し、勝者を自動選択しません。"))),
    _spec("broker-readonly", "Broker read-only query", "An explicit read-only action can issue only the allowlisted localhost GET requests. A successful GUI check is required to establish a terminal response; this inventory does not assert a live connection. No token issuance, order submission, or cancellation.",
        "broker-preview", "available", True, capabilities=("offline order mapping", "explicit localhost GET allowlist", "terminal connection not verified", "no token/submit/cancel"),
        localized_names=(("zh_CN", "券商只读查询"), ("ja_JP", "証券会社の読取専用照会")),
        localized_descriptions=(("zh_CN", "用户显式操作后才向允许的 localhost GET 接口查询；需 GUI 检查成功才可确认终端响应。本登记不表示已连接，且不发行 token、不提交或撤单。"),
            ("ja_JP", "明示操作後に許可されたlocalhost GETのみ実行します。端末応答の確認にはGUIでの成功が必要で、この一覧は接続済みを示しません。token発行・発注・取消はしません。"))),
)


def inspect_integrations(specs=DEFAULT_INTEGRATIONS, *, python_version=None,
                         python_platform=None,
                         runtime_profiles: Mapping[str, Mapping[str, object]] | None = None) -> tuple[IntegrationStatus, ...]:
    """Inspect package metadata without importing optional packages.

    ``runtime_profiles`` is injectable for tests and callers that already
    resolved a profile. No latest-run files or task directories are scanned.
    """
    result = []
    profiles = runtime_profiles or {}
    for spec in specs:
        choices = dict(spec.choices)
        profile = profiles.get(spec.id)
        if profile is None:
            profile = resolve_research_runtime(None, python_version, python_platform,
                                               operation=spec.operation, choices=choices)
        operation = profile.get("operation", {})
        packages = tuple(operation.get("packages", ())) if isinstance(operation, Mapping) else ()
        reasons = []
        dependencies_available = bool(profile.get("dependencies_available", profile.get("enabled", False)))
        if not dependencies_available:
            reasons.append(str(profile.get("reason") or "required optional dependencies are unavailable"))
        if not spec.workflow_implemented:
            reasons.append("workflow is not implemented in this public candidate")
        discoverability = [item.get("package_discoverable") for item in packages]
        package_discoverable = (all(discoverability) if discoverability else None)
        result.append(IntegrationStatus(spec,
            dependencies_available=dependencies_available,
            runtime_launchable=profile.get("runtime_launchable"),
            package_discoverable=package_discoverable,
            packages=packages,
            import_status="not_probed",
            reason="; ".join(reasons) if reasons else None))
    return tuple(result)
