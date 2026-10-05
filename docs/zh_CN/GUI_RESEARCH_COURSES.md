---
doc_id: gui_research_courses
version: 1
locale: zh_CN
---

# KabuForge GUI 研究课程（真实本地行情）

这五门课程记录的是公开候选源码检出后实际运行的 Qt 工作台，并分别用中文、日文、英文真实渲染。219 张截图是公开源码版 GUI 捕获，不是安装 wheel 后的截图，也不证明干净安装或可选 runtime 验收。公开版 Regime 默认 Off，不包含私有状态机桥接；本参考报告第 19 图为 Off/不可用、0 条轨迹，并非合格的内部状态轨迹。用户需显式选择自己的 CSV/Parquet/manifest；包内不含行情或账户数据。

五条流程使用相同的已选本地 J-Quants 日线，但不同源码运行绑定各自完成的 manifest。计算真实历史不证明当时可得。所有运行均为 **RESEARCH-ONLY，`pit_guarantee=false`**。Historical Paper 是历史研究回放，不是前向模拟；broker 只做本地映射，不连接终端、不提交或撤销订单。

<!-- section:contract -->
## 课程共用输入与固定配置

以下身份和值是三语课程共用的核对项。路径和哈希是身份，不包含原始行情；实际缓存、逐日明细、账户和完整报告只留在本机私有证据目录。

```text
codes=4502,6758,8306
reference_window=2017-01-01..2022-12-31
reference_observed_window=2017-01-04..2022-12-30
input=explicit user-selected local CSV/Parquet/snapshot/completed manifest
bundled_market_data=none
cache_ma_gui_manifest_sha256=from_local_cache_or_MA_receipt
reference_research_manifest_sha256=from_selected_research_run_receipt
public_media_manifest=docs/demos/research-20261006/media_manifest.json
public_media_manifest_sha256=from_current_acceptance_receipt
manifest_relation=distinct_bytes; same_4392_selected_raw_rows
price_basis=raw
MA_fast_slow=20/60
momentum_window=20
factor_windows=20/60; direction=positive; weights=0.5/0.5
factor_label=execution_open_to_fifth_observed_session_open
minimum_cross_section=3; quantiles=3
portfolio=top2; rebalance=monthly; initial_cash_JPY=2000000; one_way_fee=0.001
model_split=train=2017-2019; validation=2020; historical_test=2021-2022; seed=42
benchmark=local TOPIX price index; price-only; no dividends
pit_guarantee=false; status=RESEARCH-ONLY
```

代码和日期集合是为满足当前执行口径与公司行动边界而预先固定，不按收益筛选。缓存冻结时仅合并完全相同的重复记录，并显式排除经 JPX 公告确认的 2020-10-01 全日停市空行情；其他冲突或缺失不删除、不前填、不造价。TOPIX 使用本地真实价格指数，只在策略估值日期上精确对齐；不把缺口补成零或前值，也不计股息。
缓存导入/MA 冻结与后续研究运行可能绑定字节不同的 manifest，即使选择了相同的 4,392 行原始行情。请从各自的缓存、任务或报告回执读取实际 manifest SHA，不要把一个操作的哈希当作另一个操作的身份。截图参考运行的精确身份见随包文档中的 `EVIDENCE_SUMMARY.md`。截图索引则以当前 `media_manifest.json` 及其验收回执为准。

## 开始前

从公开候选源码运行工作台并选择语言。左侧包括首页、我的策略、数据中心、回测结果、纸上交易、券商连接和运行记录。在“数据中心 → 本地行情缓存 · 离线研究输入”依次完成五步：(1) 显式选择一个文件或已完成 manifest；(2) 选择证券、日期范围和研究价格口径；(3) 检查覆盖、来源身份与哈希；(4) 确认完全相同重复行及已核实停市的显式处理规则；(5) 验证、冻结并重新校验新 manifest。参考缓存回执记录去重前 8,172 行，删除 3,777 行完全相同重复记录，仅排除 2020-10-01 东证全日停市的 3 行全空占位数据，最终保留 4,392 行、1,464 个观测日。其他冲突或缺失会 fail closed，不会删除或填补。切换语言不改变输入身份。

课程使用的是本地已缓存的 J-Quants 历史数据。数据中心也提供用户明确触发的 J-Quants 连接测试/下载，但这不是课程前置步骤；本课程不读取凭证、不发网络请求。若另行下载，须遵循当前面板提示，不把下载日期当作历史 `available_at`。

公开证据摘要说明 Qt 截图来源和身份，不随包提供原始 Parquet 或完整 manifest。应按每个运行的回执核对输入 SHA。参考观测范围为 2017-01-04 至 2022-12-30，共 1,464 个共同观测日。

每个缓存任务都保留并核对 request、launch、result、exit 及 stdout/stderr 记录，确认选择参数、重复/停市计数、保留覆盖和最终 manifest SHA。可从运行记录页定位本地证据；截图本身不能代替运行回执。

![本地行情来源与选择](../demos/research-20261006/zh_CN/cache-selection.png) ![检查覆盖并冻结后的输入](../demos/research-20261006/zh_CN/cache-frozen.png)

点击主窗口“操作手册”可在应用内搜索课程全文。搜索“Demo 1”进入第一课；输入“券商”并打开匹配项可跳到 Demo 5。手册内的课程锚点和图片都来自本地文档，切换界面语言不会运行研究任务。

![应用内打开 Demo 1 手册](../demos/research-20261006/zh_CN/manual-course-demo-1.png) ![搜索券商课程并跳转](../demos/research-20261006/zh_CN/manual-search-broker.png)

## Demo 1：价格动量、MA 20/60 与指标

在“我的策略”创建新研究策略，选择“价格动量（下载数据）”模板并指定冻结输入；固定 20 日动量、每月调仓、目标持仓 2、初始资金 2,000,000 JPY、单边费率 0.1%。另选“MA 均线交叉（前收信号/次开盘）”，快慢周期为 20/60。执行前收盘检查；不得先查看 NAV 再改周期。确认通过后启动回测。

期望行为：信号仅使用前一观测日及更早的收盘，目标数量由前收盘冻结，下一观测日以实际开盘成交；同日卖单先于买单。开盘价格跳空、可用现金不足时保留原数量并整单跳过，不在开盘重新定量。NAV 以原始收盘估值。Native 与 TA-Lib MA 的冻结 recipe 下财务结果应相同；指标提供器不会改变策略金融计算。真实示例覆盖 1,464 个观测日。价格动量参考运行有 161 笔成交订单及 22 笔跳过订单；只有输入、recipe 与报告身份完全一致时才用这些数量核对。订单数不是平仓交易数。

完成后到“回测结果”，检查输入 SHA、日期、现金/持仓、费用、实际成交与跳过理由。价格图应把前收信号、实际开盘成交和跳过标记分开；跳过订单不可画成成交。原始收盘估值没有股息现金流、滑点、市场冲击或整手约束。历史 PIT 未认证，不能称作样本外或 PAPER-READY。

![Native MA 参数与输入](../demos/research-20261006/zh_CN/ma-native-configured.png) ![Native MA 结果](../demos/research-20261006/zh_CN/ma-native-results.png) ![TA-Lib MA 参数与输入](../demos/research-20261006/zh_CN/ma-talib-configured.png) ![TA-Lib MA 结果](../demos/research-20261006/zh_CN/ma-talib-results.png)

同一冻结 manifest 可在“数据中心 → 技术指标研究”独立检查图表。选一个代码，仅运行 TA-Lib 或 pandas-ta（且须有界面回执），SMA=20、RSI=14、ATR=14、MACD=12/26/9。分别读价格/SMA（JPY/股）、RSI（固定 0–100）、MACD 线/信号/柱及 ATR（JPY/股）；预热区为空值，图线在缺值处断开，不插值。ATR 使用所选数据相同口径的完整 OHLC；pandas-ta ATR 回执采用实际 provider 默认的预热 SMA seed 语义。两 provider 初始化及版本可能产生微小差异，以 receipt 中的 provider、版本和参数为准。Native 是 MA 策略计算路径，不是独立 RSI/MACD/ATR provider；指标不会自动成为信号或下单输入。

![TA-Lib 指标参数](../demos/research-20261006/zh_CN/indicator-talib-controls.png) ![TA-Lib 价格与 SMA](../demos/research-20261006/zh_CN/indicator-talib-price-sma.png) ![TA-Lib RSI](../demos/research-20261006/zh_CN/indicator-talib-rsi.png) ![TA-Lib MACD](../demos/research-20261006/zh_CN/indicator-talib-macd.png) ![TA-Lib ATR](../demos/research-20261006/zh_CN/indicator-talib-atr.png)

![pandas-ta 指标参数](../demos/research-20261006/zh_CN/indicator-pandas_ta-controls.png) ![pandas-ta 价格与 SMA](../demos/research-20261006/zh_CN/indicator-pandas_ta-price-sma.png) ![pandas-ta RSI](../demos/research-20261006/zh_CN/indicator-pandas_ta-rsi.png) ![pandas-ta MACD](../demos/research-20261006/zh_CN/indicator-pandas_ta-macd.png) ![pandas-ta ATR](../demos/research-20261006/zh_CN/indicator-pandas_ta-atr.png)

失败时检查代码是否唯一、区间 OHLC 完整、周期是否为整数、预热样本是否够，以及本地隔离运行时回执。不要为了让可选库可见而把 worker 依赖塞进主 GUI 的 NumPy/pandas 环境。复跑写入新 run，不覆盖失败记录。

## Demo 2：因子特征与独立评价

在“数据中心 → 因子诊断 · RESEARCH-ONLY”选择同一冻结 manifest。固定 20 日与 60 日动量、正向权重各 0.5、秩标准化、最小横截面 3、3 分位、前向标签 5 个观测日，确认 recipe 后运行。

先看“特征/recipe”页，确认每一条 feature 是信号日 D-1 可计算字段；`feature_rows` 与评价标签文件分离。标签定义为执行日开盘至之后第 5 个观测日开盘的简单收益。它只进入 evaluation panel，尾部无未来窗口的记录保留为空，不是策略输入。随后检查每日 IC/Rank IC、覆盖/样本数、分位收益、分位成员换手、因子相关和年度描述统计。常量因子、缺失横截面、零有效日期应显示原因；同值按代码确定性分桶不代表有信息。三只股票最多三分位，重叠标签不能增加独立样本量；ICIR 是描述性均值/标准差，不作未经校准的统计推断。

不要用标签、分位收益或评价面板训练/回测策略，也不要按这段历史挑方向和权重。需要复现时保留 `contract.json`、`receipt.json`、`report.json` 和该 run 的日志；课程图像不包含原始行行情。异常输入或缺共同日期时，应按回执定位缺失/来源问题，不去掉失败证券来制造完整覆盖。

![因子诊断工作区](../demos/research-20261006/zh_CN/factor-workbench.png) ![固定特征和 recipe](../demos/research-20261006/zh_CN/factor-input-and-recipe.png) ![IC 与 Rank IC](../demos/research-20261006/zh_CN/factor-ic-rank-ic.png) ![分位收益](../demos/research-20261006/zh_CN/factor-quantiles.png) ![覆盖](../demos/research-20261006/zh_CN/factor-coverage.png) ![成员换手](../demos/research-20261006/zh_CN/factor-turnover.png) ![因子相关](../demos/research-20261006/zh_CN/factor-correlation.png) ![年度描述统计](../demos/research-20261006/zh_CN/factor-observed-years.png)

## Demo 3：组合、固定时间切分模型与引擎候选

打开“数据中心 → Research Studio”。在“策略”页显式选择 `factor_feature_rows`（feature-only）或明确的模型 `predictions`，选择文件后核对字节 SHA。不要选 evaluation/forward-label 文件。固定两持仓、月频、2,000,000 JPY、单边费用 0.1%、最小横截面 3；正向 20/60 各 0.5 的合成分数不因表现变更。运行后核对每个 signal date、execution date、实际成交/跳过及每日 NAV。

在“模型”页选冻结因子 run，并运行 LightGBM 与 CatBoost 两种固定模型。时间切分固定为训练 2017–2019、验证 2020、历史诊断 2021–2022，seed 42，按标签结束日期 purge 分区边界；无随机切分、自动调参或自动择优。模型仅在训练标签截止之后可用。训练拟合预测留作诊断，策略 predictions 不应包含训练期；2021–2022 已被观察，不是新 OOS。检查边界、purge 数、样本数、缺失原因、模型/预测 SHA。若缺隔离依赖，使用失败阶段/worker 日志；不要在主进程尝试导入库。

在“引擎”页对相同 manifest 和冻结订单 recipe 分别查看 Native、VectorBT、Backtrader 实际报告。这里是固定候选复播，不重新定量或搬用 Native NAV。比较账户日序列与逐笔 fills（日期、方向、数量、实际开盘价、费用）、skips 与费用；`daily_account_within_tolerance` 和 `execution_stream_matches` 是不同结论。引擎有现金、整数量/long-only语义差异时保留差异，不能因期末现金接近就称完全相同。Backtrader 的下一 bar market 事件也不等于 broker 实际成交。

![20/60 因子组合参数](../demos/research-20261006/zh_CN/studio-factor-composite-controls.png) ![因子组合结果](../demos/research-20261006/zh_CN/studio-factor-composite-results.png) ![两模型参数](../demos/research-20261006/zh_CN/studio-both-models-controls.png) ![LightGBM 评分策略结果](../demos/research-20261006/zh_CN/studio-lightgbm-score-results.png) ![CatBoost 参数](../demos/research-20261006/zh_CN/studio-catboost-score-controls.png) ![CatBoost 评分策略结果](../demos/research-20261006/zh_CN/studio-catboost-score-results.png) ![两模型结果](../demos/research-20261006/zh_CN/studio-both-models-results.png) ![两模型剩余结果](../demos/research-20261006/zh_CN/studio-both-models-remaining-results.png)

![引擎参数](../demos/research-20261006/zh_CN/studio-engines-20-60-controls.png) ![引擎摘要](../demos/research-20261006/zh_CN/studio-engines-20-60-results.png) ![引擎剩余结果](../demos/research-20261006/zh_CN/studio-engines-20-60-remaining-results.png)

读取组合报告时先看账户路径、订单计划、费用和报告/来源哈希，再看图。真实 TOPIX 是固定的价格指数基准，不含股息，按相同 NAV 估值日期完整对齐；缺日期时相对统计应不可用。现有仪表盘为 19 张图（15 张总体图、3 张个股价格/执行图、1 张 Regime 状态图）。当前报告中的该图为 Off/不可用、0 条轨迹，没有合格的状态轨迹；费用与执行延迟敏感性已由独立面板完成运行和财务路径验收，单独于这 19 张图展示。模型及引擎输出仍为 RESEARCH-ONLY/PIT=false。

## 结果图的读法（jQuantStats 风险统计 + 真实价格执行图）

打开结果页后先确认运行模型、频率、样本日期、价格口径、费用、TOPIX 来源和 `pit_guarantee=false`。jQuantStats 对相邻 NAV 的 N−1 段收益做风险/收益统计，不包含初始资金到首个 NAV 的区间；应用原生 NAV/总区间收益按报告本身的初始资金口径展示，二者不可混称。日频年化为 252 观测期，前提是报告声明 `daily`；不能因自然日或缺失日期把这当成真实交易所日历。

仪表盘按顺序提供 15 组总体图：jQuantStats 相邻 NAV 收益快照、原报告 NAV、水下回撤、月度收益热力图、观察窗口年度收益、滚动收益/波动/Sharpe、策略与 TOPIX 累计收益、区间收益分布、现金与持仓权重、FIFO 费用后已平仓交易收益、累计已实现净盈亏、累计实际费用、双边总成交换手、持仓数/最大权重/HHI、可核验的证券价格贡献。其后还有每只证券一张价格诊断图，以及 Regime 面板。本参考报告中的面板为 Off/不可用、0 条轨迹；只有其他报告提供合格历史输入时才会显示时间线。年度图表示观察窗口，不保证完整日历年；jQuantStats 使用相邻 NAV 的 N−1 段收益，不包含初始资金到首个 NAV。日频年化按 252 期，仅当报告明确声明 `daily` 才适用。悬停核对日期、单位、缺值和数值轴；成交订单数、fill 数与已平仓周期数不同。

另看“价格、前收信号与次日执行”图：实线原始价格与指标、前收订单计划标记、实际开盘成交标记、跳过订单标记含义各异。悬停的 signal date 早于 execution date；成交价格不是信号价格。TOPIX 虚线只表示未含股息的价格指数，不是可投资总回报。已扣实际费用不能重复扣费；gross turnover 是买卖双边总额，不能叫单边换手。订单计数、成交计数与完整平仓周期不同。

![Native MA 结果页](../demos/research-20261006/zh_CN/ma-native-results.png) ![TA-Lib MA 结果页](../demos/research-20261006/zh_CN/ma-talib-results.png)

组合贡献、集中度和有内容的 Regime 时间线仅在报告携带可核验输入时显示。当前截图中的 Regime 面板为 Off/不可用、0 条轨迹。费用与延迟敏感性已由回测结果页的独立面板运行并完成独立财务路径验收，不属于 19 张绩效仪表盘图；它绑定当前来源 report 的字节 SHA 并生成独立离线任务。图表帮助解释运行结果，不验证策略有效性。

![jQuantStats 快照](../demos/research-20261006/zh_CN/dashboard-chart-01.png) ![月收益热力图](../demos/research-20261006/zh_CN/dashboard-chart-04.png) ![TOPIX 对照](../demos/research-20261006/zh_CN/dashboard-chart-07.png) ![价格、信号与执行](../demos/research-20261006/zh_CN/dashboard-chart-16.png) ![Regime 关闭、不可用、0 条轨迹](../demos/research-20261006/zh_CN/dashboard-chart-19.png)

完整 19 图截图索引： [01 jQuantStats 快照](../demos/research-20261006/zh_CN/dashboard-chart-01.png) · [02 NAV](../demos/research-20261006/zh_CN/dashboard-chart-02.png) · [03 回撤](../demos/research-20261006/zh_CN/dashboard-chart-03.png) · [04 月热力图](../demos/research-20261006/zh_CN/dashboard-chart-04.png) · [05 年度观察窗](../demos/research-20261006/zh_CN/dashboard-chart-05.png) · [06 滚动风险](../demos/research-20261006/zh_CN/dashboard-chart-06.png) · [07 TOPIX](../demos/research-20261006/zh_CN/dashboard-chart-07.png) · [08 收益分布](../demos/research-20261006/zh_CN/dashboard-chart-08.png) · [09 持仓/现金](../demos/research-20261006/zh_CN/dashboard-chart-09.png) · [10 平仓收益](../demos/research-20261006/zh_CN/dashboard-chart-10.png) · [11 已实现盈亏](../demos/research-20261006/zh_CN/dashboard-chart-11.png) · [12 费用](../demos/research-20261006/zh_CN/dashboard-chart-12.png) · [13 双边换手](../demos/research-20261006/zh_CN/dashboard-chart-13.png) · [14 集中度](../demos/research-20261006/zh_CN/dashboard-chart-14.png) · [15 价格贡献](../demos/research-20261006/zh_CN/dashboard-chart-15.png) · [16 4502 价格/执行](../demos/research-20261006/zh_CN/dashboard-chart-16.png) · [17 6758 价格/执行](../demos/research-20261006/zh_CN/dashboard-chart-17.png) · [18 8306 价格/执行](../demos/research-20261006/zh_CN/dashboard-chart-18.png) · [19 Regime 关闭/不可用、0 条轨迹](../demos/research-20261006/zh_CN/dashboard-chart-19.png)

### 成本与执行延迟敏感性：绑定来源并运行全部情景

在“回测结果”打开完成的来源 `report.json`，确认路径、策略和输入身份，再核对面板“来源运行”显示的 report 路径与 **report SHA256**。若 SHA 与你选中的文件不一致，或报告不是带冻结研究输入的价格研究结果，先停止；不要手改源报告。点击“运行三个固定情景”后，应用通过离线 QProcess 工作进程运行，显示 3 行、3 条 NAV 曲线，全部情景都会保留，不自动选择“最好”的结果。仅切换中/日/英界面语言只重绘现有结果，不重新运行；来源 report 字节保持不变。

三个预先固定情景含义不同：0.1% 是基线策略重跑；0.2% 用同一策略、冻结行情和其余配方重新运行，费用储备变化会重新计算前收盘订单数量。`+1 观测日` 不重新产生信号或选股，冻结基线订单数量，并在下一实际观测日开盘执行，是执行时点诊断，不是新策略，也不能和费用情景的重新定量混为一谈。三个情景日期均为 2017-01-04 至 2022-12-30，共 1,464 个观测日。表中结束权益、NAV、费用与成交结果只描述固定历史回放，不代表样本外或实时表现。

| 来源运行（report SHA256） | 情景 | 订单 | 成交 / 跳过 | 费用 JPY | 期末 NAV | 期末现金 / 权益 JPY | 最大回撤 |
|---|---|---:|---:|---:|---:|---:|---:|
| Native MA `Native MA report (SHA bound locally)` | 0.1% 基线重跑 | 64 | 45 / 19 | 64,251.25 | 1.10859189 | 13.94 / 2,217,183.77 | -30.70% |
| Native MA 同上 | 0.2% 费用重跑 | 64 | 45 / 19 | 126,492.57 | 1.07504194 | 13.53 / 2,150,083.89 | -31.38% |
| Native MA 同上 | +1 日、固定数量 | 64 | 30 / 34 | 34,828.99 | 2.16391987 | 146,472.52 / 4,327,839.74 | -31.63% |
| TA-Lib MA `TA-Lib MA report (SHA bound locally)` | 0.1% 基线重跑 | 64 | 45 / 19 | 64,251.25 | 1.10859189 | 13.94 / 2,217,183.77 | -30.70% |
| TA-Lib MA 同上 | 0.2% 费用重跑 | 64 | 45 / 19 | 126,492.57 | 1.07504194 | 13.53 / 2,150,083.89 | -31.38% |
| TA-Lib MA 同上 | +1 日、固定数量 | 64 | 30 / 34 | 34,828.99 | 2.16391987 | 146,472.52 / 4,327,839.74 | -31.63% |
| 价格动量 `price-momentum report (SHA bound locally)` | 0.1% 基线重跑 | 183 | 161 / 22 | 92,328.74 | 1.38670855 | 1,276,821.14 / 2,773,417.11 | -33.10% |
| 价格动量 同上 | 0.2% 费用重跑 | 184 | 168 / 16 | 182,846.64 | 1.25358260 | 9,737.31 / 2,507,165.19 | -41.32% |
| 价格动量 同上 | +1 日、固定数量 | 183 | 128 / 55 | 59,240.38 | 1.32007157 | 192,816.23 / 2,640,143.15 | -38.01% |

SHA 在表中以首尾缩写呈现，实际完整值由界面、请求和回执绑定。Native MA 与 TA-Lib MA 的三种情景在本次固定输入下财务路径一致；价格动量来源是独立固定的离线研究报告，不是 GUI 运行回执，面板仍按其 report 字节 SHA 绑定。不要把延迟案例较高的期末 NAV 当作择优理由。公开来源任务记录 request/source 哈希和 worker launch/result/exit 日志；摘要不发布私有逐日 JSON。金额显示到小数点后两位，复核请以绑定报告和账户路径为准。

![Native MA 敏感性面板](../demos/research-20261006/zh_CN/sensitivity-native-workbench.png) ![Native MA 三情景结果](../demos/research-20261006/zh_CN/sensitivity-native-results.png)
![TA-Lib MA 敏感性面板](../demos/research-20261006/zh_CN/sensitivity-talib-workbench.png) ![TA-Lib MA 三情景结果](../demos/research-20261006/zh_CN/sensitivity-talib-results.png)
![价格动量敏感性面板](../demos/research-20261006/zh_CN/sensitivity-momentum-workbench.png) ![价格动量三情景结果](../demos/research-20261006/zh_CN/sensitivity-momentum-results.png)

## Demo 4：历史 Paper 逐步、全量与只读恢复

左侧选“纸上交易”→首个 tab“真实行情历史研究模拟”（不要进入第二个“高级旧版功能”）。显式选择已冻结 manifest、已完成的价格/组合报告，并指定全新的研究账户目录。确认初始资金、订单计划和输入身份；点击“创建隔离账户”。绝不选择生产账户或旧账本。

点“打开并核验”只读验证。然后用“推进一天”观察一个下一日期；该日无成交时检查 cash/NAV 和 skip，而不是误认为任务没运行。选择实际成交日时，核对信号日、执行日、次日开盘、方向、数量、费用和成交回执。点击“完整回放”顺序处理剩余观察日，期望覆盖完整 1,464 个已观察日并到 2022-12-30；以报告及完成回执为准，不能把起止申请区间的自然日数量当成样本数。最终比较完成标记、账户路径摘要、fills/skips/fees 与原报告。

![创建独立账户](../demos/research-20261006/zh_CN/paper-created.png) ![单步回放](../demos/research-20261006/zh_CN/paper-one-observed-day.png) ![实际成交日](../demos/research-20261006/zh_CN/paper-actual-trade-day.png) ![完整历史回放](../demos/research-20261006/zh_CN/paper-full-history.png) ![最后观测日](../demos/research-20261006/zh_CN/paper-last-observed-day.png) ![重开后只读查看](../demos/research-20261006/zh_CN/paper-reopened-readonly.png)

关闭后重新打开同一教学账户，再次“打开并核验”并“只读刷新”。只读查询不得推进日期；同一 cursor/idempotency key 的重试不得复制事件/成交。若来源 manifest、报告字节、选中数据或回放实现身份变化，必须 fail closed，保留旧回执并新建账户解决。通过 GUI 任务/历史页面查看本地 request/result/exit 与日志；公开证据摘要不包含账本或逐日账户数据。历史时间是 replay clock，不是行情 `available_at`；该连续份额研究账本不代表前向 paper、真实整手成交或券商执行。

## Demo 5：测试端配置、合法/阻断映射与只读边界

左侧选“券商连接”→首个 tab“离线现金股票映射预览”。第二个“高级旧版能力表”不是连接确认页。创建新的配置工作区，选测试环境 `http://127.0.0.1:18081`。本地标签、账户类别和交易所为明确教学字段；凭证字段只可为引用字符串，不能粘贴密钥。保存配置只写本地配置文件，不解析引用、不创建 token。

按教学输入建 `OrderIntent`：代码 6758、买入、数量 100、标的 lot size 100、tick size 1、东京时区且有效时间在 DAY 窗口内；预览所需的教学参考价、费用、账户和时钟从课程任务固定配置输入，不能照搬行情缓存当实时报价。点“生成本地映射预览”。期望显示 mapped locally / not connected / not submitted，映射请求与输入 SHA 在本地 receipt 中，`network_calls=0`。不要按提交、撤单或 token 按钮——本课程没有这些入口。

此次固定本地配置为测试端口 18081、指定账户类型（4）及 SOR 交易所（9）。这些编号只是 mapper 字段。参考价、fee、账户标签与教学时钟按独立课程配置输入；缓存收盘价不是实时行情。成功回执应显示 `network_calls=0`。

![测试端口配置](../demos/research-20261006/zh_CN/broker-test-config.png) ![合法整手离线映射](../demos/research-20261006/zh_CN/broker-valid-local-mapping.png)

将数量改成 101 后再次预览，期望以 lot 阻断、`network_calls=0`，失败 receipt 只记脱敏错误码，不保存订单 payload；修正为整手数量后可再预览。broker 课程私有证据保留 `broker_config.json`、成功预览、failure request/result 与运行日志；三语真实截图均已归档。

只读连接检查是独立能力，不能从保存配置或离线预览推导。执行显式缺引用负例：填入本轮专用且预期不存在的环境引用 `env:DEMO_MISSING_TOKEN`，保存后点击“只读检查”。worker 应在凭证解析阶段以 `credential_missing` 失败，GET 数为 0；配置只保存引用名而非秘密值。这是失败诊断，不是连接成功。若引用可解析，显式检查会启动 localhost GET worker 并可能联系终端，本课程只使用预期不存在的引用。三语缺引用诊断截图已归档；能力页标记 workflow implemented 不代表实际终端已验证。生产端口 18080 不是本课目标。

<!-- section:evidence -->
## 截图、日志与恢复索引

219 张图均由公开候选源码运行 Qt 并在各语言界面实际捕获，不是私有工作台截图，也不证明安装 wheel 已验收。仪表盘由 15 张总体图、3 张个股价格/执行图和 1 张 Regime 图组成；敏感性是独立面板。media manifest 记录截图路径与哈希。

| 课程 | 归档目标路径（`{locale}` 为 `zh_CN` / `ja_JP` / `en_US`） |
|---|---|
| 冻结行情 | `../demos/research-20261006/{locale}/cache-{selection,frozen}.png` |
| MA | `../demos/research-20261006/{locale}/ma-{native,talib}-{configured,results}.png` |
| 结果仪表盘 | `../demos/research-20261006/{locale}/dashboard-chart-01.png` 至 `dashboard-chart-19.png`；16–18 分别为 4502/6758/8306 价格执行图，19 显示 Regime Off/不可用、0 条轨迹 |
| 指标 | `../demos/research-20261006/{locale}/indicator-{talib,pandas_ta}-{controls,price-sma,rsi,macd,atr}.png` |
| 因子 | `../demos/research-20261006/{locale}/factor-{input-and-recipe,ic-rank-ic,quantiles,coverage,turnover,correlation,observed-years}.png` |
| Studio | `../demos/research-20261006/{locale}/studio-factor-composite-{controls,results}.png`、`studio-both-models-{controls,results,remaining-results}.png`、`studio-lightgbm-score-results.png`、`studio-catboost-score-{controls,results}.png`、`studio-engines-20-60-{controls,results,remaining-results}.png` |
| 历史 Paper | `../demos/research-20261006/{locale}/paper-{created,one-observed-day,actual-trade-day,full-history,last-observed-day,reopened-readonly}.png` |
| Broker | `../demos/research-20261006/{locale}/broker-{test-config,valid-local-mapping,blocked-101,readonly-missing-reference}.png`（均已归档） |
| 成本与延迟敏感性 | `../demos/research-20261006/{locale}/sensitivity-{native,talib,momentum}-{workbench,results}.png` |
| 手册搜索 | `../demos/research-20261006/{locale}/manual-course-demo-1.png`、`manual-search-broker.png` |

公开证据摘要位于 `docs/demos/research-20261006/EVIDENCE_SUMMARY.md`，只概述已公开截图的来源身份、范围和限制。应用运行日志可从 GUI 任务/历史页定位；公开包不携带本地请求、原始账本、详细 JSON 或用户绝对路径。

敏感性截图和验收范围见公开证据摘要 `docs/demos/research-20261006/EVIDENCE_SUMMARY.md`。三来源各三个固定情景均完成独立财务路径核验；这里不发布私有日度明细或完整回执。

全部材料说明离线研究与历史回放，不证明真实交易、当时数据可见、严格 PIT、样本外表现或 PAPER-READY。任何未随报告提供或未通过资格检查的 Regime 输入仍为 unavailable。


