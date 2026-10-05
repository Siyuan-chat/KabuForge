---
doc_id: development
version: 1
locale: zh_CN
---

# 开发

<!-- section:contract -->
## 合约

应面向软件包边界开发，不要依赖 GUI 内部或配置驱动导入。既有 `ApplicationService.register_factor(id, version, function, validator)` 与 `StrategyRegistry.register(StrategySpec, factory)` API 继续受支持；校验器必需，重复身份会被拒绝。较新的 `ResearchApplicationService` 是面向已支持固定研究操作、受 workspace 限制的 facade。它接收显式文件引用和 recipe，把选定的可选操作委托给静态 worker，并留存请求/源码哈希、回执和失败日志。GUI、CLI、MCP 各自遵循支持范围和 allowlist；不能假设所有旧界面或命令都经过该 facade。它不接收用户 Python、任意模块路径或解释器命令。

使用确定性的本地夹具。本地缓存研究不会推断历史 `available_at`；此类结果一律为 RESEARCH-ONLY，`pit_guarantee=false`。原始研究数据、凭证、券商传输和私有实现不得进入公共发行物。模拟成交、计划意图或 CLI 成功退出都不能证明真实执行。

公开源码中的 GUI 与 worker 流程已验证，覆盖显式选择本地数据、默认价格动量、指标、因子/模型/引擎研究、结果报告、隔离 Historical Paper 与券商映射/只读边界。Python API 和 14 条固定 CLI/MCP 研究路由也已通过源码验证。修改工作流前请阅读[集成能力矩阵](INTEGRATIONS.md)和[五条 GUI 研究课程](GUI_RESEARCH_COURSES.md)。

<!-- section:evidence -->
## 证据

公开包名为 `kabuforge`，要求 Python 3.12+，项目自有材料采用 AGPL-3.0-only，并保留第三方许可通知。候选版本 `0.2.0rc1` 尚未发布，入口为 `kabuforge = kabuforge.cli:main`。`public_source_manifest.json` 固定公开源码身份；源码检查本身不证明 wheel 已安装或 GUI 已运行。

GUI extra 安装在 Python 3.12 环境中。`pyproject.toml` 声明了可选依赖组 `analytics`、`indicators`、`models`、`backends`；按需选择，不必全部安装。是否成功运行某个可选操作，应看 worker 回执，不仅看 package metadata 或能力发现结果。

```powershell
python -m pip install -e ".[gui]"
python -m framework_v2.cli --help
python -B -m unittest discover -s framework_v2/tests -q
python -B -m unittest discover -s tools/tests -p "test_sync_version.py" -q
```

从源码检出启动桌面工作台：

```powershell
python -B -m framework_v2.workbench_qt
```

该命令会打开交互式 GUI，不是 headless 或无人值守测试命令。若要声明发行包验收，必须绑定到确切的 wheel 文件名、SHA-256、版本、Python/平台及安装后模块来源，并针对该安装包运行相应 GUI/worker 检查。源码检出截图和源码测试不能证明已安装 wheel。`0.2.0rc1` 尚未发布。
