"""User-facing async strategy, model and engine research workflows."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import sysconfig
import uuid
from datetime import datetime, timezone

from PySide6.QtCore import QProcess, QProcessEnvironment, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget)


_WORKER_ENVIRONMENT_KEYS = frozenset({
    "SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
})


_TEXT = {
    "zh_CN": {"title":"研究 Studio · RESEARCH-ONLY", "manifest":"当前冻结清单", "pick":"选择评分文件…",
        "strategy":"评分策略", "model":"模型训练", "engine":"引擎比较", "source":"评分来源",
        "features":"因子特征（不含前向标签）", "predictions":"模型预测", "score":"预测文件",
        "factor":"因子运行目录", "model_name":"训练模型", "both":"两种模型（全部报告）",
        "lgb":"LightGBM", "cat":"CatBoost", "train":"训练选定模型", "pick_factor":"选择因子运行目录…",
        "pick_prediction":"选择 predictions.json…", "count":"持仓数", "frequency":"频率",
        "monthly":"每月", "weekly":"每周", "daily":"每日", "run_strategy":"运行评分策略回测",
        "lookback":"预注册动量窗口", "lb20":"20 日", "lb60":"60 日", "run_engine":"运行两引擎比较",
        "running":"后台运行中…", "idle":"请选择冻结输入并启动工作流。结果标记为 RESEARCH-ONLY。",
        "done":"已完成。所有候选均显示，不自动挑选。", "failed":"失败：", "stale":"输入在任务运行期间已变化，旧结果已丢弃。",
        "need_factor":"请先完成因子诊断，再选择其运行目录。", "missing_runtime":"当前 Python 环境缺少所选工作流依赖：",
        "score_hash":"评分文件 SHA-256（字节）", "price_only":"TOPIX 与账户结果由结果页按冻结行情日期配对；历史可见性未认证。",
        "partial":"部分完成；请逐项检查候选状态。", "details":"查看运行证据", "model_available":"预测文件已就绪，可在评分策略页明确选择后运行。",
        "split_note":"固定时间切分：训练 2017–2019 → 验证 2020 → 历史诊断 2021–2022；训练前按标签结束时间 purge。", "engine_note":"Native 固定订单计划由 VectorBT 与 Backtrader 重放；不改变信号、数量或财务路径。",
        "days":"观测日", "end_nav":"期末归一化净值", "fills":"已成交订单", "skips":"跳过订单", "fees":"累计费用", "training":"训练", "validation":"验证", "test":"历史诊断", "rows":"有效样本", "rmse":"RMSE", "mae":"MAE", "candidate":"候选", "backend":"后端", "agreement":"一致性", "use_prediction":"使用所选预测作为评分", "status":"状态", "match":"与 Native 一致", "diverge":"与 Native 不一致", "partial_rows":"候选/接受/边界剔除/标签缺失", "open_report":"打开回测结果", "cash":"期末现金", "mdd":"最大回撤"},
    "ja_JP": {"title":"Research Studio · RESEARCH-ONLY", "manifest":"現在の凍結マニフェスト", "pick":"スコアファイルを選択…",
        "strategy":"スコア戦略", "model":"モデル学習", "engine":"エンジン比較", "source":"スコアソース",
        "features":"ファクター特徴量（将来ラベルなし）", "predictions":"モデル予測", "score":"予測ファイル",
        "factor":"ファクター実行フォルダー", "model_name":"学習モデル", "both":"両モデル（全結果表示）",
        "lgb":"LightGBM", "cat":"CatBoost", "train":"選択モデルを学習", "pick_factor":"ファクター実行を選択…",
        "pick_prediction":"predictions.json を選択…", "count":"保有数", "frequency":"頻度",
        "monthly":"月次", "weekly":"週次", "daily":"日次", "run_strategy":"スコア戦略を実行",
        "lookback":"事前登録モメンタム窓", "lb20":"20日", "lb60":"60日", "run_engine":"2エンジンを比較",
        "running":"バックグラウンド実行中…", "idle":"凍結入力を選択して実行してください。結果は RESEARCH-ONLY です。",
        "done":"完了。全候補を表示し、自動選択しません。", "failed":"失敗：", "stale":"実行中に入力が変更されました。古い結果を破棄しました。",
        "need_factor":"先にファクター診断を実行し、その実行フォルダーを選択してください。", "missing_runtime":"現在の Python 環境に選択したワークフローの依存パッケージがありません：",
        "score_hash":"スコアファイル SHA-256（バイト）", "price_only":"TOPIX と口座結果は結果画面で凍結データの日付を照合します。過去の可視性は未認証です。",
        "partial":"一部完了。候補ごとの状態を確認してください。", "details":"実行証拠を表示", "model_available":"予測ファイルを選択できます。スコア戦略タブで明示的に選択して実行してください。",
        "split_note":"固定時系列分割：学習 2017–2019 → 検証 2020 → 過去診断 2021–2022。学習前にラベル終了日で purge。", "engine_note":"Native の固定注文計画を VectorBT と Backtrader で再生します。シグナル・数量・財務経路は変更しません。",
        "days":"観測日", "end_nav":"期末正規化NAV", "fills":"約定注文", "skips":"スキップ注文", "fees":"累積費用", "training":"学習", "validation":"検証", "test":"過去診断", "rows":"採用行数", "rmse":"RMSE", "mae":"MAE", "candidate":"候補", "backend":"エンジン", "agreement":"一致状況", "use_prediction":"選択した予測をスコアに使用", "status":"状態", "match":"Native と一致", "diverge":"Native と不一致", "partial_rows":"候補/採用/境界除外/ラベル欠損", "open_report":"バックテスト結果を開く", "cash":"期末現金", "mdd":"最大ドローダウン"},
    "en_US": {"title":"Research Studio · RESEARCH-ONLY", "manifest":"Active frozen manifest", "pick":"Choose score file…",
        "strategy":"Score strategy", "model":"Model training", "engine":"Engine comparison", "source":"Score source",
        "features":"Factor features (no forward labels)", "predictions":"Model predictions", "score":"Prediction file",
        "factor":"Factor run directory", "model_name":"Models to train", "both":"Both models (report all)",
        "lgb":"LightGBM", "cat":"CatBoost", "train":"Train selected models", "pick_factor":"Choose factor run…",
        "pick_prediction":"Choose predictions.json…", "count":"Holdings", "frequency":"Frequency",
        "monthly":"Monthly", "weekly":"Weekly", "daily":"Daily", "run_strategy":"Run score strategy",
        "lookback":"Preregistered momentum window", "lb20":"20 sessions", "lb60":"60 sessions", "run_engine":"Compare both engines",
        "running":"Running in a background process…", "idle":"Select frozen inputs and start a workflow. Results are RESEARCH-ONLY.",
        "done":"Completed. All candidates are shown; none is auto-selected.", "failed":"Failed: ", "stale":"Input changed while the task ran; its result was discarded.",
        "need_factor":"Run factor diagnostics first, then select its output directory.", "missing_runtime":"Selected workflow dependencies are unavailable in the active Python environment: ",
        "score_hash":"Score file SHA-256 (bytes)", "price_only":"TOPIX is paired by exact frozen-data dates on the result page; historical visibility is unverified.",
        "partial":"Partially completed; inspect each candidate status.", "details":"Show run evidence", "model_available":"Prediction file is ready. Select it explicitly on the Score strategy tab before running.",
        "split_note":"Fixed time split: train 2017–2019 → validation 2020 → historical diagnostic 2021–2022; purge by label end before each boundary.", "engine_note":"VectorBT and Backtrader replay the fixed Native order schedule; signals, quantities and finance are unchanged.",
        "days":"Observed sessions", "end_nav":"Ending normalized NAV", "fills":"Filled orders", "skips":"Skipped orders", "fees":"Total fees", "training":"Train", "validation":"Validation", "test":"Historical diagnostic", "rows":"Accepted rows", "rmse":"RMSE", "mae":"MAE", "candidate":"Candidate", "backend":"Backend", "agreement":"Agreement", "use_prediction":"Use selected predictions as score", "status":"Status", "match":"Matches Native", "diverge":"Differs from Native", "partial_rows":"Candidates/accepted/boundary-purged/missing-label", "open_report":"Open backtest results", "cash":"Ending cash", "mdd":"Maximum drawdown"},
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new_json(path: Path, payload: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


class ResearchStudioPanel(QGroupBox):
    """Three bounded workflows over explicitly selected local research artifacts."""
    strategy_report_ready = Signal(object)

    def __init__(self, workspace, factor_panel, language="zh_CN", parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace).resolve()
        self.factor_panel = factor_panel
        self.language = language if language in _TEXT else "zh_CN"
        self.manifest_path: Path | None = None
        self.process: QProcess | None = None
        self._busy = False
        self._generation = 0
        self._active_generation = None
        self._active_job = None
        self._active_operation = None
        self._terminal_handled = False
        self._raw_result = ""
        self._strategy_report = None
        self._closed = False
        self.last_result = None
        self.setProperty("ownTranslation", True)

        root = QVBoxLayout(self)
        self.manifest_label = QLabel(); self.manifest_label.setWordWrap(True); root.addWidget(self.manifest_label)
        self.tabs = QTabWidget(); root.addWidget(self.tabs)
        self.strategy_tab = QWidget(); self.model_tab = QWidget(); self.engine_tab = QWidget()
        self.tabs.addTab(self.strategy_tab, "")
        self.tabs.addTab(self.model_tab, "")
        self.tabs.addTab(self.engine_tab, "")
        self._build_strategy(); self._build_model(); self._build_engine()
        self.status = QLabel(); self.status.setWordWrap(True); root.addWidget(self.status)
        self.open_report_button = QPushButton(); self.open_report_button.clicked.connect(self._open_strategy_report); self.open_report_button.setEnabled(False); root.addWidget(self.open_report_button)
        self.result = QPlainTextEdit(); self.result.setReadOnly(True); self.result.setMaximumBlockCount(3000); root.addWidget(self.result, 1)
        self.details_button = QPushButton(); self.details_button.setCheckable(True); self.details_button.toggled.connect(self._toggle_details); root.addWidget(self.details_button)
        self.set_language(self.language)
        self._update_enabled()

    def _build_strategy(self):
        layout = QVBoxLayout(self.strategy_tab); form = QFormLayout(); layout.addLayout(form)
        self.score_source = QComboBox(); self.score_source.addItem("", "factor_feature_rows"); self.score_source.addItem("", "model_predictions")
        self.score_path = QLineEdit(); self.score_path.setReadOnly(True)
        self.pick_score = QPushButton(); self.pick_score.clicked.connect(self._pick_score)
        row = QWidget(); row_layout = QHBoxLayout(row); row_layout.setContentsMargins(0,0,0,0); row_layout.addWidget(self.score_path,1); row_layout.addWidget(self.pick_score)
        self.score_hash_label = QLabel(); self.count = QSpinBox(); self.count.setRange(1,3); self.count.setValue(2)
        self.frequency = QComboBox()
        for key in ("monthly","weekly","daily"): self.frequency.addItem("", key)
        self.source_label = QLabel(); self.count_label = QLabel(); self.frequency_label = QLabel()
        form.addRow(self.source_label, self.score_source); form.addRow(self.score_hash_label, row)
        form.addRow(self.count_label, self.count); form.addRow(self.frequency_label, self.frequency)
        self.run_strategy_button = QPushButton(); self.run_strategy_button.clicked.connect(self.run_strategy); layout.addWidget(self.run_strategy_button)

    def _build_model(self):
        layout = QVBoxLayout(self.model_tab); form = QFormLayout(); layout.addLayout(form)
        self.split_note = QLabel(); self.split_note.setWordWrap(True); layout.addWidget(self.split_note)
        self.factor_path = QLineEdit(); self.factor_path.setReadOnly(True)
        self.pick_factor = QPushButton(); self.pick_factor.clicked.connect(self._pick_factor)
        row = QWidget(); row_layout = QHBoxLayout(row); row_layout.setContentsMargins(0,0,0,0); row_layout.addWidget(self.factor_path,1); row_layout.addWidget(self.pick_factor)
        self.model_names = QComboBox()
        self.model_names.addItem("", "both"); self.model_names.addItem("", "lightgbm"); self.model_names.addItem("", "catboost")
        self.factor_label = QLabel(); self.model_label = QLabel()
        form.addRow(self.factor_label, row); form.addRow(self.model_label, self.model_names)
        self.train_button = QPushButton(); self.train_button.clicked.connect(self.train_models); layout.addWidget(self.train_button)
        self.prediction_picker = QPushButton(); self.prediction_picker.clicked.connect(self._pick_prediction); layout.addWidget(self.prediction_picker)
        prediction_row = QWidget(); prediction_layout = QHBoxLayout(prediction_row); prediction_layout.setContentsMargins(0,0,0,0)
        self.prediction_model = QComboBox(); self.use_prediction_button = QPushButton(); self.use_prediction_button.clicked.connect(self._use_prediction)
        prediction_layout.addWidget(self.prediction_model,1); prediction_layout.addWidget(self.use_prediction_button); layout.addWidget(prediction_row)
        self.prediction_path = QLineEdit(); self.prediction_path.setReadOnly(True); layout.addWidget(self.prediction_path)

    def _build_engine(self):
        layout = QVBoxLayout(self.engine_tab)
        self.engine_intro = QLabel(); self.engine_intro.setWordWrap(True); layout.addWidget(self.engine_intro)
        self.lookback20 = QCheckBox(); self.lookback60 = QCheckBox(); self.lookback20.setChecked(True)
        layout.addWidget(self.lookback20); layout.addWidget(self.lookback60)
        self.run_engine_button = QPushButton(); self.run_engine_button.clicked.connect(self.compare_engines); layout.addWidget(self.run_engine_button)

    def set_manifest(self, path):
        candidate = Path(path).expanduser().resolve() if path else None
        candidate = candidate if candidate and candidate.is_file() else None
        if candidate == self.manifest_path: return
        self._generation += 1
        self.manifest_path = candidate
        self.factor_path.clear(); self.score_path.clear(); self.score_path.setToolTip("")
        self.prediction_path.clear(); self.prediction_model.clear()
        self._strategy_report = None; self.open_report_button.setEnabled(False)
        if self._busy:
            self.status.setText(_TEXT[self.language]["stale"])
        else:
            self.last_result = None; self.result.clear()
            self.status.setText(_TEXT[self.language]["idle"])
        self.manifest_label.setText((str(candidate) if candidate else "—"))
        self._update_enabled()

    def clear_manifest(self): self.set_manifest(None)

    @property
    def busy(self): return self._busy

    def set_language(self, language):
        self.language = language if language in _TEXT else "zh_CN"; t = _TEXT[self.language]
        self.setTitle(t["title"]); self.tabs.setTabText(0,t["strategy"]); self.tabs.setTabText(1,t["model"]); self.tabs.setTabText(2,t["engine"])
        self.manifest_label.setText(t["manifest"] + ": " + (str(self.manifest_path) if self.manifest_path else "—"))
        self.score_source.setItemText(0,t["features"]); self.score_source.setItemText(1,t["predictions"])
        self.source_label.setText(t["source"]); self.count_label.setText(t["count"]); self.frequency_label.setText(t["frequency"])
        self.pick_score.setText(t["pick"]); self.score_hash_label.setText(t["score_hash"])
        self.count.setPrefix(t["count"] + " "); self.frequency.setItemText(0,t["monthly"]); self.frequency.setItemText(1,t["weekly"]); self.frequency.setItemText(2,t["daily"])
        self.run_strategy_button.setText(t["run_strategy"]); self.pick_factor.setText(t["pick_factor"])
        self.factor_label.setText(t["factor"]); self.model_label.setText(t["model_name"])
        self.model_names.setItemText(0,t["both"]); self.model_names.setItemText(1,t["lgb"]); self.model_names.setItemText(2,t["cat"])
        self.train_button.setText(t["train"]); self.prediction_picker.setText(t["pick_prediction"])
        self.use_prediction_button.setText(t["use_prediction"])
        self.lookback20.setText(t["lookback"] + " · " + t["lb20"]); self.lookback60.setText(t["lookback"] + " · " + t["lb60"])
        self.engine_intro.setText(t["price_only"] + " · " + t["engine_note"])
        self.split_note.setText(t["split_note"])
        self.run_engine_button.setText(t["run_engine"])
        self.details_button.setText(t["details"])
        self.open_report_button.setText(t["open_report"])
        if self._busy: self.status.setText(t["running"])
        if not self._busy and self.last_result is None: self.status.setText(t["idle"])
        elif not self._busy and self.last_result is not None:
            self.status.setText(t["failed"] + str(self.last_result.get("reason", "FAILED")) if self.last_result.get("status") == "FAILED"
                else t["partial"] if self.last_result.get("status") == "PARTIAL" else t["done"])
            self.result.setPlainText(self._summary_text(self.last_result))

    def _factor_run(self):
        report = getattr(self.factor_panel, "report", None)
        if not isinstance(report, dict): raise ValueError(_TEXT[self.language]["need_factor"])
        input_identity = report.get("input_identity", {})
        if not self.manifest_path or input_identity.get("manifest_sha256") != _sha256(self.manifest_path):
            raise ValueError(_TEXT[self.language]["stale"])
        run_dir = Path(report.get("artifacts", {}).get("contract", "")).resolve().parent
        if not (run_dir / "feature_rows.json").is_file(): raise ValueError(_TEXT[self.language]["need_factor"])
        return run_dir

    def _pick_factor(self):
        try: initial = str(self._factor_run())
        except Exception: initial = str(self.workspace / "factor-research")
        path = QFileDialog.getExistingDirectory(self, _TEXT[self.language]["pick_factor"], initial)
        if path: self.factor_path.setText(path)

    def _pick_score(self):
        try:
            if self.score_source.currentData() == "factor_feature_rows":
                path = self._factor_run() / "feature_rows.json"
            else:
                start = self.prediction_path.text() or str(self.workspace)
                picked, _ = QFileDialog.getOpenFileName(self, _TEXT[self.language]["pick_prediction"], start, "predictions.json (predictions.json)")
                path = Path(picked) if picked else None
            if path and path.is_file(): self.score_path.setText(str(path)); self.score_path.setToolTip(_sha256(path))
        except Exception as exc: self.status.setText(str(exc))

    def _pick_prediction(self):
        path, _ = QFileDialog.getOpenFileName(self, _TEXT[self.language]["pick_prediction"], str(self.workspace), "predictions.json (predictions.json)")
        if path and Path(path).name == "predictions.json":
            self.prediction_path.setText(path)
            self.prediction_model.clear(); self.prediction_model.addItem(Path(path).parent.name, path)
            self.score_source.setCurrentIndex(1); self.score_path.setText(path); self.score_path.setToolTip(_sha256(Path(path)))

    def _use_prediction(self):
        path = self.prediction_model.currentData()
        if not path:
            path = self.prediction_path.text()
        candidate = Path(path).expanduser().resolve() if path else None
        if not candidate or not candidate.is_file() or candidate.name != "predictions.json":
            self.status.setText(_TEXT[self.language]["failed"] + "select a completed predictions.json artifact")
            return False
        self.prediction_path.setText(str(candidate)); self.score_path.setText(str(candidate))
        self.score_path.setToolTip(_sha256(candidate)); self.score_source.setCurrentIndex(1); self.tabs.setCurrentIndex(0)
        return True

    def _runtime_environment(self, operation, request_body=None):
        from .research_runtime import resolve_extension_runtime, resolve_research_runtime
        python = platform.python_version()
        plat = "win-amd64" if os.name == "nt" and sys.maxsize > 2**32 else sysconfig.get_platform()
        project_root = Path(__file__).resolve().parents[1]
        body = request_body or {}
        if operation == "model_training":
            choices = {"model_names": body.get("model_names") or [self.model_names.currentData()]}
            runtime = resolve_extension_runtime(project_root, python, plat,
                operation="model-training", choices=choices)
        elif operation == "engine_comparison":
            runtime = resolve_extension_runtime(project_root, python, plat,
                operation="engine-comparison", choices={"backends": ["vectorbt", "backtrader"]})
        else:
            runtime = resolve_research_runtime(project_root, python, plat, operation="native")
        if not runtime.get("enabled"):
            raise RuntimeError(_TEXT[self.language]["missing_runtime"] + str(runtime.get("reason")))
        paths = runtime.get("paths", [])
        inherited = QProcessEnvironment.systemEnvironment()
        env = QProcessEnvironment()
        for name in inherited.keys():
            if name.upper() in _WORKER_ENVIRONMENT_KEYS:
                env.insert(name, inherited.value(name))
        root = str(Path(__file__).resolve().parents[1])
        env.insert("PYTHONPATH", os.pathsep.join([*paths, root]))
        env.insert("PYTHONDONTWRITEBYTECODE", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        return env

    def _start(self, operation, body):
        if self._busy or not self.manifest_path: return False
        try:
            env = self._runtime_environment(operation, body)
            job_id = uuid.uuid4().hex
            job_dir = self.workspace / "research-studio" / "jobs" / job_id
            job_dir.mkdir(parents=True, exist_ok=False)
            request = {"schema":"kabuforge.research_studio_request.v1", "job_id":job_id, "operation":operation, **body}
            with (job_dir / "request.json").open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(request, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write("\n")
            for filename in ("stdout.log", "stderr.log"):
                (job_dir / filename).touch(exist_ok=False)
            process = QProcess(self)
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
            process.setProcessEnvironment(env); process.setProgram(sys.executable)
            process.setArguments(["-B", "-u", "-m", "framework_v2.research_studio_worker", "--workspace", str(self.workspace), "--job-id", job_id])
            process.setStandardOutputFile(str(job_dir / "stdout.log")); process.setStandardErrorFile(str(job_dir / "stderr.log"))
            process.finished.connect(lambda code, status, p=process, folder=job_dir, generation=self._generation: self._process_finished(p, folder, generation, code, status))
            process.errorOccurred.connect(lambda error, p=process: self._process_error(p, error))
            process.started.connect(lambda p=process, folder=job_dir, req=request, program=sys.executable, args=process.arguments():
                self._record_launch(p, folder, req, program, args))
            self._busy = True; self._generation_at_start = self._generation
            self._active_job = job_dir; self._active_operation = operation; self._terminal_handled = False
            self.last_result = None; self._strategy_report = None; self.open_report_button.setEnabled(False)
            self.result.clear(); self.details_button.setChecked(False)
            self.status.setText(_TEXT[self.language]["running"]); self._update_enabled()
            self.process = process; self._active_operation = operation; process.start()
            return True
        except Exception as exc:
            self.status.setText(_TEXT[self.language]["failed"] + str(exc)); return False

    def _base_request(self):
        manifest = self.manifest_path.resolve(strict=True)
        return {"manifest_path": str(manifest), "manifest_sha256": _sha256(manifest)}

    def run_strategy(self):
        try:
            if self.score_source.currentData() == "factor_feature_rows" and not self.score_path.text(): self._pick_score()
            score = Path(self.score_path.text()).resolve(strict=True)
            source = self.score_source.currentData()
            if score.name != ("feature_rows.json" if source == "factor_feature_rows" else "predictions.json"):
                raise ValueError("score source must match feature_rows.json or predictions.json")
            recipe = {"schema":"kabuforge.factor_score_strategy_recipe.v1", "count":self.count.value(),
                "frequency":str(self.frequency.currentData()), "cash":2_000_000.0, "fee":0.1, "minimum_cross_section":3}
            body = {**self._base_request(), "score_path":str(score), "score_sha256":_sha256(score), "score_source":source, "recipe":recipe}
            return self._start("factor_strategy", body)
        except Exception as exc: self.status.setText(_TEXT[self.language]["failed"]+str(exc)); return False

    def train_models(self):
        try:
            run_dir = Path(self.factor_path.text()).resolve(strict=True) if self.factor_path.text() else self._factor_run()
            choice = self.model_names.currentData(); names = ["lightgbm","catboost"] if choice == "both" else [choice]
            bundle = {name: _sha256(run_dir / name) for name in ("contract.json", "report.json", "feature_rows.json", "evaluation_panel.json")}
            return self._start("model_training", {**self._base_request(), "factor_run_dir":str(run_dir),
                "factor_bundle_sha256":bundle, "model_names":names})
        except Exception as exc: self.status.setText(_TEXT[self.language]["failed"]+str(exc)); return False

    def compare_engines(self):
        if not self.lookback20.isChecked() and not self.lookback60.isChecked():
            self.status.setText(_TEXT[self.language]["failed"]+"select at least one preregistered lookback"); return False
        recipes = [{"signal_template":"price_momentum", "lookback":window, "count":2, "frequency":"monthly", "cash":2_000_000.0, "fee":0.1}
                   for window, checked in ((20,self.lookback20.isChecked()),(60,self.lookback60.isChecked())) if checked]
        return self._start("engine_comparison", {**self._base_request(), "recipes":recipes})

    def _process_error(self, process, error):
        if process is self.process and process.state() == QProcess.ProcessState.NotRunning:
            self._fail_to_start(process, error)

    def _record_launch(self, process, job_dir, request, program, arguments):
        try:
            request_sha = _sha256(job_dir / "request.json")
            identity = {key: request.get(key) for key in ("manifest_path", "manifest_sha256", "score_path",
                "score_sha256", "score_source", "factor_run_dir", "factor_bundle_sha256", "recipes") if key in request}
            _write_new_json(job_dir / "launch.json", {"schema":"kabuforge.research_studio_launch.v1",
                "job_id":job_dir.name, "operation":request.get("operation"), "started_at_utc":datetime.now(timezone.utc).isoformat(),
                "pid":int(process.processId()), "program":str(program), "arguments":list(arguments),
                "request_sha256":request_sha, "input_identity":identity,
                "logs":{"stdout":str(job_dir/"stdout.log"),"stderr":str(job_dir/"stderr.log")},
                "recovery_point":str(job_dir), "exit_policy":"wait for process completion; no forced termination"})
        except (OSError, ValueError):
            # A missing launch receipt is surfaced in the terminal receipt; never affect the worker.
            pass

    def _record_exit(self, job_dir, exit_code, exit_status, error=None):
        if not job_dir: return
        if not (job_dir / "launch.json").exists():
            launch = {"schema":"kabuforge.research_studio_launch.v1", "job_id":job_dir.name,
                "operation":self._active_operation, "started_at_utc":None, "pid":None,
                "program":sys.executable, "arguments":[], "request_sha256":_sha256(job_dir/"request.json"),
                "logs":{"stdout":str(job_dir/"stdout.log"),"stderr":str(job_dir/"stderr.log")},
                "recovery_point":str(job_dir), "exit_policy":"process failed to start; no child process was created"}
            try: _write_new_json(job_dir/"launch.json", launch)
            except (OSError, ValueError): pass
        receipt = {"schema":"kabuforge.research_studio_exit.v1", "job_id":job_dir.name,
            "operation":self._active_operation, "ended_at_utc":datetime.now(timezone.utc).isoformat(),
            "exit_code":exit_code, "exit_status":getattr(exit_status,"name",str(exit_status)),
            "error":error, "logs":{"stdout":str(job_dir/"stdout.log"),"stderr":str(job_dir/"stderr.log")},
            "result":str(job_dir/("result.json" if (job_dir/"result.json").is_file() else "failure.json"))}
        try: _write_new_json(job_dir/"exit.json", receipt)
        except (OSError, ValueError): pass

    def _fail_to_start(self, process, error):
        if process is not self.process or self._terminal_handled: return
        self._terminal_handled = True
        job_dir = self._active_job
        error_text = process.errorString()
        error_value = getattr(error, "value", None)
        failure = {"schema":"kabuforge.research_studio_failure.v1", "job_id":job_dir.name if job_dir else None,
            "operation":self._active_operation, "status":"FAILED", "error_type":"QProcessStartError",
            "reason":error_text, "process_error":error_value if isinstance(error_value, int) else str(error),
            "readiness":"RESEARCH-ONLY", "pit_guarantee":False}
        if job_dir and not (job_dir / "failure.json").exists():
            try: (job_dir / "failure.json").write_text(json.dumps(failure,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            except OSError: pass
        self._record_exit(job_dir, None, None, error_text)
        self._busy = False; self.process = None; process.deleteLater(); self._update_enabled()
        if not self._closed:
            self.last_result = failure; self.status.setText(_TEXT[self.language]["failed"] + error_text)
            self._raw_result = json.dumps(failure,ensure_ascii=False,indent=2); self.result.setPlainText(failure["reason"])

    def _process_finished(self, process, job_dir, generation, exit_code, exit_status):
        if process is not self.process or self._terminal_handled: return
        self._terminal_handled = True
        self._record_exit(job_dir, exit_code, exit_status)
        self._busy = False; self.process = None; process.deleteLater(); self._update_enabled()
        if self._closed: return
        path = job_dir / ("result.json" if (job_dir / "result.json").is_file() else "failure.json")
        try: result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            self.status.setText(_TEXT[self.language]["failed"] + f"worker exit={exit_code}, result receipt missing ({job_dir})"); return
        request_path = job_dir / "request.json"
        try: request = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError): request = {}
        valid_identity = (isinstance(result, dict) and result.get("job_id") == job_dir.name
            and result.get("operation") == self._active_operation
            and request.get("job_id") == job_dir.name and request.get("operation") == self._active_operation
            and result.get("schema") in {"kabuforge.research_studio_result.v1", "kabuforge.research_studio_failure.v1"})
        if not valid_identity:
            self.status.setText(_TEXT[self.language]["failed"] + "worker receipt identity/schema mismatch"); return
        try: current_manifest_sha = _sha256(self.manifest_path) if self.manifest_path else None
        except OSError: current_manifest_sha = None
        expected_manifest_sha = request.get("manifest_sha256") if isinstance(request, dict) else None
        if (not expected_manifest_sha or expected_manifest_sha != current_manifest_sha
                or (result.get("status") != "FAILED" and result.get("manifest_sha256") != expected_manifest_sha)):
            self.status.setText(_TEXT[self.language]["stale"]); return
        if self._active_operation == "factor_strategy" and result.get("status") != "FAILED":
            report_path = Path(result.get("report_path", "")).resolve()
            try: report_hash = _sha256(report_path)
            except (OSError, ValueError): report_hash = None
            if (not report_path.is_relative_to((job_dir / "outputs").resolve())
                    or not report_hash or report_hash != result.get("report_sha256")):
                self.status.setText(_TEXT[self.language]["failed"] + "strategy report hash/path validation failed"); return
        if generation != self._generation:
            self.status.setText(_TEXT[self.language]["stale"]); return
        self.last_result = result
        if result.get("status") == "FAILED" or exit_code != 0:
            self.status.setText(_TEXT[self.language]["failed"] + str(result.get("reason", result.get("status"))))
        elif result.get("status") == "PARTIAL":
            self.status.setText(_TEXT[self.language]["partial"])
        else:
            self.status.setText(_TEXT[self.language]["done"])
        self._raw_result = json.dumps(result, ensure_ascii=False, indent=2)[:1_000_000]
        self._strategy_report = None
        if result.get("operation") == "factor_strategy" and result.get("status") != "FAILED":
            try:
                report_path = Path(result["report_path"]).resolve(strict=True)
                self._strategy_report = json.loads(report_path.read_text(encoding="utf-8"))
            except (KeyError, OSError, UnicodeError, json.JSONDecodeError):
                self.status.setText(_TEXT[self.language]["failed"] + "strategy report could not be loaded"); return
            if (not isinstance(self._strategy_report, dict)
                    or self._strategy_report.get("model") != "daily_bar_next_open_research_v1"
                    or self._strategy_report.get("input_identity", {}).get("manifest_sha256") != expected_manifest_sha):
                self.status.setText(_TEXT[self.language]["failed"] + "unsupported strategy report schema"); return
            self.open_report_button.setEnabled(True)
        self.result.setPlainText(self._summary_text(result))
        if result.get("operation") == "model_training":
            ready = [item for item in result.get("model_runs", []) if item.get("status") == "COMPLETED" and item.get("prediction_path")]
            self.prediction_model.clear()
            for item in ready:
                self.prediction_model.addItem(item.get("model_name", "model"), item["prediction_path"])
            if ready:
                suffix = _TEXT[self.language]["model_available"]
                self.status.setText((_TEXT[self.language]["partial"] + "\n" if result.get("status") == "PARTIAL" else "") + suffix)
        if result.get("operation") == "factor_strategy" and isinstance(self._strategy_report, dict):
            self.strategy_report_ready.emit(self._strategy_report)

    def _summary_text(self, result):
        t = _TEXT[self.language]
        if result.get("operation") == "factor_strategy":
            report = self._strategy_report or {}
            nav = report.get("nav", []); trades = report.get("trades", []); skips = report.get("skipped_orders", [])
            last = nav[-1] if nav else {}
            return (f"RESEARCH-ONLY · {report.get('model','')}\n{t['days']}: {len(nav)} | {nav[0].get('at','—') if nav else '—'} – {last.get('at','—')}\n"
                f"{t['end_nav']}: {last.get('nav','—')}\n{t['fills']}: {len(trades)} | {t['skips']}: {len(skips)} | {t['fees']} JPY: {report.get('fees','—')}\n{t['price_only']}")
        if result.get("operation") == "model_training":
            rows = ["RESEARCH-ONLY · " + t["split_note"]]
            for run in result.get("model_runs", []):
                rows.append(f"\n{run.get('model_name')} · {run.get('status')}")
                if run.get("status") == "COMPLETED":
                    for split in ("train","validation","test"):
                        metrics = run.get("metrics", {}).get(split, {})
                        counts = run.get('split_counts',{}).get(split,{})
                        date_range = f"{counts.get('signal_date_min') or '—'}–{counts.get('signal_date_max') or '—'}"
                        rows.append(f"{t[split]} {date_range}: {t['partial_rows']}={counts.get('candidate_feature_rows','—')}/{counts.get('accepted_rows','—')}/{counts.get('purged_label_boundary','—')}/{counts.get('excluded_missing_label','—')} · {t['rmse']}={metrics.get('rmse','—')} · {t['mae']}={metrics.get('mae','—')}")
                    rows.append(f"training label cutoff={run.get('model_training_label_end_max','—')} · prediction artifact: {run.get('prediction_path','')}")
                else: rows.append(str(run.get("reason", "")))
            return "\n".join(rows)
        rows = ["RESEARCH-ONLY · " + t["engine_note"]]
        for candidate in result.get("candidates", []):
            rows.append(f"\n{t['candidate']} {candidate.get('candidate')} · {candidate.get('status')}")
            summary = candidate.get("native_summary", {})
            rows.append(f"{summary.get('start_date','—')} – {summary.get('end_date','—')} · {t['days']}={summary.get('observed_sessions','—')} · {t['end_nav']}={summary.get('ending_normalized_nav','—')} · {t['cash']}={summary.get('ending_cash','—')} JPY")
            rows.append(f"{t['fills']}={summary.get('fills','—')} · {t['skips']}={summary.get('skips','—')} · {t['fees']}={summary.get('fees','—')} JPY · {t['mdd']}={summary.get('max_drawdown_from_reported_nav','—')}")
            for backend, backend_value in candidate.get("backend_status", {}).items():
                rows.append(f"{t['backend']} {backend}: {backend_value.get('status','—')}")
            for backend, comparison in candidate.get("comparison_status", {}).items():
                label = t["match"] if comparison == "MATCHED_WITHIN_TOLERANCE" else t["diverge"]
                detail = next((item for item in candidate.get("comparisons", []) if item.get("backend") == backend), {})
                rows.append(f"{t['agreement']} {backend}: {label} · daily Δ={detail.get('daily_account_exceedances','—')} · fills Δ={detail.get('fill_differences','—')} · skips Δ={detail.get('skip_differences','—')} · fee Δ={detail.get('fee_difference','—')}")
            if candidate.get("reason"): rows.append(str(candidate["reason"]))
        return "\n".join(rows)

    def _toggle_details(self, checked):
        if self._raw_result:
            self.result.setPlainText(self._raw_result if checked else self._summary_text(self.last_result or {}))

    def _open_strategy_report(self):
        if isinstance(self._strategy_report, dict): self.strategy_report_ready.emit(self._strategy_report)

    def _update_enabled(self):
        ready = self.manifest_path is not None and not self._busy
        for widget in (self.tabs, self.run_strategy_button, self.train_button, self.run_engine_button,
                       self.pick_score, self.pick_factor, self.prediction_picker, self.count, self.frequency,
                       self.model_names, self.lookback20, self.lookback60, self.use_prediction_button,
                       self.prediction_model): widget.setEnabled(ready)
        self.open_report_button.setEnabled(bool(self._strategy_report and not self._busy))

    def closeEvent(self, event):
        if self._busy:
            event.ignore(); return
        self._closed = True; event.accept()
