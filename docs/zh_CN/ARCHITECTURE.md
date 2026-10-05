---
doc_id: architecture
version: 1
locale: zh_CN
---

# 架构

<!-- section:contract -->
## 契约

KabuForge 保留两个契约不同的服务层。既有 `ApplicationService` 是旧版决策边界：它解析经过校验的配置，使用白名单因子与策略注册表，分离研究价格和执行报价，并返回计划。它不会提交订单、写入账本或联系券商。策略配置只能选择已注册实现身份，不会动态导入代码。使用该层的既有调用方仍遵守 `available_at` 与执行时间线规则。

共享 `ResearchApplicationService` 是固定本地研究核心的适配层，不是新的金融计算引擎。它接收显式文件引用和固定 recipe，校验选中输入及源码身份，在工作区边界内创建任务产物，并保留请求、启动、成功/失败回执和日志。CLI 与 MCP 共提供 14 项固定研究操作，各自使用独立白名单；GUI 也有自己的操作边界，并非所有旧界面或命令都经过该 facade。适配器不为已调用的固定核心另写一套计算。请求不能携带代码、模块导入、shell 命令或解释器路径。模型、指标和回测后端等可选依赖按具体操作检查，并由已定义的静态 worker 执行；GUI 主进程不导入这些重型可选库。

不能混淆两种输入契约。旧版快照可要求明确的 `available_at` 和可见性校验。本地历史日线研究则明确冻结用户选择的 CSV、Parquet、snapshot 或已完成 manifest，记录覆盖范围、研究价格口径、来源／选择哈希及假设，不会补造历史可用时间。结果为 `RESEARCH-ONLY`，`pit_guarantee=false`。

Agent facade 保留独立的工作区边界、JSON Schema 校验、凭证扫描、持久调用回执和本地 SQLite 审计状态。它不能访问 `.git`、`.aws`、`.codex`、secret、credential 或审计数据库。历史 Paper 是显式 opt-in 后新建的隔离追加式研究回放，不是旧执行账本，也不是实时或前向 Paper 账户。

离线券商映射使用不发起调用的 transport，不解析 secret。另一个必须显式发起的只读检查会解析已配置引用，并向指定本地 endpoint 发送 cash、positions、orders 三种 GET。真实券商终端尚未验证。提交和撤销订单保持禁用。R3 不在默认 MCP catalog 中；展示保留的 stub 不会启用它，也不授予权限。

<!-- section:evidence -->
## 证据

旧版策略注册表默认注册 `composite_factor` 版本 `1`，内置因子身份来自本地 `BuiltinFactors`。新的研究流程默认使用价格动量。本地行情冻结与因子缓存均显式绑定输入身份；只有接入缓存的因子策略路径使用该缓存，不代表旧版全体行情／因子流程已经复用缓存。因子特征行与远期标签评价行分开保存。固定的 LightGBM/CatBoost 模型使用时间顺序训练／验证／历史测试分段，并清除跨越边界的标签。Native、VectorBT、Backtrader 独立回放冻结订单；账户路径一致不代表所有输入的逐笔成交流完全相同。

指标只有 TA-Lib 与 native `pandas-ta` 两类 provider。静态 worker gate 按操作检查可选运行环境，而不是在 GUI 主进程导入所有可选库。结果 dashboard 使用深色 19 图布局（15 张汇总图、3 张逐证券价格／执行图、1 张 Regime 图），费用／延迟固定情景另有独立面板。TOPIX 是不含分红的价格指数，仅按 NAV 日期精确匹配连接。参考报告中的 Regime 图为 Off／不可用，trace 数为 0；公开版本默认关闭 Regime，且不包含私有状态机桥接。内置离线帮助有 24 个可搜索章节，包含三语研究课程。

源码候选 `0.2.0rc1` 尚未发布。公开 GUI／worker 工作流以及 Python、CLI、MCP 研究路由已针对源码验证。任何发行版验收声明都必须绑定具体 wheel 文件名、SHA-256、版本、Python／平台与安装后的模块来源，并记录该安装制品上按操作执行的检查；源码截图和源码测试不能代替安装包证据。示例中的数据由用户提供，不随包分发。历史报告为 RESEARCH-ONLY／PIT false，不是严格 PIT、新鲜 OOS、PAPER-READY 或真实执行证据。
