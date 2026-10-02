---
doc_id: strategy_api
version: 1
locale: zh_CN
---

# 策略 API 与扩展开发指南

[English](../en_US/STRATEGY_API.md) · [简体中文](../zh_CN/STRATEGY_API.md) · [日本語](../ja_JP/STRATEGY_API.md)

请先阅读[因子 API](FACTOR_API.md)。本指南说明当前策略注册契约，不是券商执行 API。统一链路为 Factor → StrategyDecision → TargetPortfolio → RiskPolicy → Planner → OrderIntent。

<!-- section:contract -->
## 1. 实现注册层的决策契约

```python
from typing import Mapping, Protocol
from kabuforge.api import FactorContext, FactorResult, StrategyDecision, StrategyState


class Strategy(Protocol):
    def decide(
        self, *, results: Mapping[str, FactorResult], context: FactorContext,
        state: StrategyState, decision_identity: str, rebalance: bool = True,
    ) -> StrategyDecision:
        ...
```

以上为接口签名。工厂接收 `(config, factor_ids)`，返回带有 `decide` 方法的对象；类构造器也可以作为工厂。不要求继承特定基类，而是按接口结构检查。工厂应拒绝自身不支持的设置。只能由可信应用代码注册，配置不能导入任意代码。

| 输入 | 含义 |
| --- | --- |
| `results` | 配置因子 ID 到已校验 `FactorResult` 的映射；键不是算法实现 ID。 |
| `context` | 只读时点数据和本次决策时刻。 |
| `state` | 上次决策返回的显式状态，或初始 `StrategyState()`。 |
| `decision_identity` | 本次决策的身份。内置适配器拒绝重复处理上次身份；独立实现也应保留等价检查。 |
| `rebalance` | 本次是否请求新目标，默认 `True`。 |

**兼容性易错点：** `framework_v2.strategy.CompositeFactorStrategy.decide()` 返回 `(target, state)`，不是注册层要求的结果对象。应使用 `CompositeFactorStrategyAdapter`，其 `decide()` 调用 `decide_with_audit()` 并返回 `StrategyDecision`。本例通过适配器保留绑定、日期、缺失值、公式和重复决策检查。

## 2. 返回完整决策，而不是订单

`StrategyDecision` 需要全部九个字段：

| 字段 | 用途 |
| --- | --- |
| `target` | 完整 `TargetPortfolio`，或表示不调仓的 `None`。 |
| `state` | 新的 `StrategyState`，应传给下一次决策。 |
| `scores` | 每个代码对应的有限评分。 |
| `ranked_codes`、`dropped_codes` | 确定性的排序和明确剔除的代码。 |
| `preprocess`、`missing_policy` | 实际采用的处理政策。 |
| `factor_inputs`、`factor_processed` | 各因子、各代码的原始值与处理后值，供审查。 |

独立的非评分型策略可在合理时使用空审计映射，但仍应诚实填写契约，不虚构评分或证据。这并不解除当前文件 schema 对评分配置的要求。

```python
from kabuforge.api import TargetPortfolio

no_rebalance = None
liquidate_to_cash = TargetPortfolio.from_weights({})
full_target = TargetPortfolio.from_weights({"SYN_A": "0.5"})
```

三个值含义不同。`None` 不请求调仓，保持当前配置；空目标请求清仓到现金；非空目标表示**整个期望组合**，不是新增买入指令，未在目标中列出的原有持仓以零为目标。清仓请求经风控和规划后可能受到限制，或只能部分完成。

权重使用有限 `Decimal`。`TargetPortfolio.cash_residual` 表示 `1 - long_gross`，不是账户实际现金，也不是 `1 - net`。目标类型能够表达负权重，但不意味着执行层已经支持卖空或实盘券商。

`StrategyState` 包含 `last_decision_identity`、`regime`、`cooldown_until` 和 JSON 兼容的 `transition_state`，可通过 `to_json()` / `from_json()` 显式持久化。状态字段本身不实现市场状态或冷却期算法。应用每次规划都会通过工厂创建策略，因此不要依赖策略实例的可变属性跨决策存续。

## 3. 定义策略配置

本例会生成完全一致的 `strategy.json`：

```json
{
  "schema_version": "1.0",
  "id": "extension_demo",
  "version": "1",
  "kind": "strategy",
  "implementation": {
    "id": "example.positive_score",
    "version": "1"
  },
  "universe": {
    "snapshot": "universe"
  },
  "factors": [
    "factor.json"
  ],
  "scoring": {
    "formula": "price_change"
  },
  "portfolio": {
    "construction": "equal_weight",
    "parameters": {
      "top_n": 1,
      "preprocess": "none",
      "missing_policy": "reject"
    }
  },
  "risk": {
    "max_position_weight": 0.5,
    "max_gross_exposure": 1,
    "turnover_budget": 2,
    "allow_short": false
  },
  "rebalance": {
    "frequency": "daily"
  }
}
```

`factors` 是相对于策略文件的因子配置路径；`scoring.formula` 使用**因子配置中的 ID**，这里是 `price_change`，不是 `factor.json` 或 `example.price_change`。解析器在规划前检查完整的 run → strategy → factors 引用图与内容身份。

`implementation` 选择已注册策略。v1 配置省略它时，仅选择 `composite_factor` 版本 `"1"`；配置自己的 `version` 不决定算法版本。尽管 schema 也描述了股票池路径形式，当前应用规划路径要求 `universe: {"snapshot": "universe"}`。

### 内置组合策略的行为

适配器支持因子 ID、有限常数、`+`、`-`、`*`、`/` 与一元正负号，不支持函数调用、属性访问、索引或任意求值。预处理为 `none`、`zscore` 或 `rank`；缺失值显式选择 `reject` 或 `drop`。候选集合是股票池与全部引用因子非缺失代码的交集，同分时按代码打破平局。

它选择高分多头和剩余股票中的低分空头，各侧等权并使用明确的总敞口。`portfolio.construction: "rank"` 目前只是等权构建的别名，**不是按排名比例配权**。空头目标仍受后续执行能力约束。

### 当前扩展边界

选择自定义工厂不会创建自定义配置格式。[strategy.schema.json](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/schemas/strategy.schema.json) 仍要求 factors、评分公式、组合、风险和调仓字段，并限制组合参数名称；解析器仍会验证公式。无因子的事件策略或新增优化器参数区块，需要未来明确修改 schema 与集成，不能通过添加未定义 JSON 字段实现。

schema 接受 daily、weekly、monthly 调仓设置，但 `ApplicationService.plan()` 自身不计算该调仓日历，而是按默认 `rebalance=True` 调用 `decide`。声明频率不等于调用方已经执行它；应在合适的调用方或明确实现的策略逻辑中落实调度，并测试实际路径。

## 4. 注册可信工厂

```python
from kabuforge.api import ApplicationService, StrategyRegistry, StrategySpec
from examples.extension_demo import PositiveScoreStrategy

registry = StrategyRegistry()
registry.register(
    StrategySpec("example.positive_score", "1"), PositiveScoreStrategy,
)
app = ApplicationService(strategy_registry=registry)
```

此处只注册策略。校验运行前，还需在同一应用服务注册所需因子；`examples/extension_demo.py:build_service()` 展示了两者。未知或重复身份会失败，目录按实现 ID 和版本排序。注册表仅存在于当前服务内存中，不会安装包入口，也不会让另一个 CLI、GUI 或 MCP 进程自动加载扩展。需要使用该扩展的前端应接入同一套可信启动注册逻辑。

示例 `PositiveScoreStrategy` 将评分委托给适配器；当没有任何处理后评分为正时，请求空的现金目标，并通过 `dataclasses.replace` 保留审计信息与新状态。不调仓时保留 `target=None`。该示例拒绝空头选股，只用于教学，不是已验证的投资策略。

## 5. 连接运行配置与规划层

本例的 `run.json` 为：

```json
{
  "schema_version": "1.0",
  "id": "extension_demo_run",
  "version": "1",
  "kind": "run",
  "strategy": "strategy.json",
  "data_snapshot": "snapshot.json",
  "clock": {
    "start": "2024-05-01",
    "end": "2024-05-01",
    "timezone": "Asia/Tokyo"
  },
  "mode": "fake",
  "fees": {
    "commission_rate": 0,
    "minimum_fee": 0
  },
  "account_ref": "account.json",
  "output_dir": "output"
}
```

生成的同级文件包括 `factor.json`、`strategy.json`、`snapshot.json` 和 `account.json`。引用路径相对于包含该引用的文件解析。零费用、账户和价格均为合成示例，不是现实执行假设。

`app.validate(run_path)` 解析并校验配置；随后 `app.plan(...)` 接收已解析运行、身份匹配的 `FactorContext`、`AccountState`、分开的研究参考价与执行报价、交易品种信息、明确带时区的 `now`，以及可选的前次状态和能力声明。返回 `RunResult`，包含因子结果、决策、风险决策和订单计划。服务本身不提交订单，也不写执行账本。

研究参考价属于决策快照。后续执行报价可以限制订单计划，但不能反过来选择先前的研究目标。策略之后先应用风险政策，再进行交易单位、价格、现金等规划检查。计划成功不等于成交。

在源码仓库根目录，使用 Python 3.12+：

```shell
python -m pip install -e .
python examples/extension_demo.py --out output/extension_demo
python -m unittest discover -s framework_v2/tests -p test_extension_example.py -v
```

使用新输出目录，或省略 `--out` 改用临时目录。示例只运行一次决策，输出原始目标、允许目标、风控原因和计划订单数，并标记 `orders_submitted: false`。它不是历史回测、模拟成交或真实交易。

<!-- section:evidence -->
## 6. 测试、目录与常见错误

完整实现见 [extension_demo.py](https://github.com/Siyuan-chat/KabuForge/blob/main/examples/extension_demo.py)。[test_extension_example.py](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/tests/test_extension_example.py) 检查注册后的应用链路、命令行、缺失值政策、未来输入和结果、不调仓与清仓、重复决策、状态序列化，以及三语配置示例。现有 CI 会发现该测试模块，不需要为此修改工作流命令。

| 现象 | 检查方向 |
| --- | --- |
| 未知策略 | 在当前服务注册精确的实现 ID/版本。 |
| 返回了二元组而不是决策 | 使用注册层适配器契约，不使用旧 `decide()` 简写。 |
| JSON 参数不支持 | 遵守现有 schema；登记工厂不是扩展 schema。 |
| 重复决策 | 传递并持久化返回状态，不静默重放相同身份。 |
| 意外清仓 | 不要用空目标替换 `None`，两者刻意区分。 |
| 原始目标与允许目标不同 | 查看 `RunResult.risk` 和订单规划原因，不用执行价反向改写研究信号。 |
| 另一个进程找不到自定义策略 | 在该前端接入可信注册逻辑；注册不是全局的。 |

`list_strategies` 与 `describe_strategy` 提供目录信息，`plan_strategy` 在规划前校验运行和执行引用。这些是 agent 工具，不是策略协议的方法；它们不授予任意代码加载或实盘下单权限。以代码为准：[策略注册表](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/strategy_registry.py)、[决策模型](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/models.py)、[内置策略与风控](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/strategy.py)、[应用服务](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/application.py)。另见[执行说明](EXECUTION.md)和 [Agent API](AGENT_API.md)。
