---
doc_id: factor_api
version: 1
locale: zh_CN
---

# 因子 API 与扩展开发指南

[English](../en_US/FACTOR_API.md) · [简体中文](../zh_CN/FACTOR_API.md) · [日本語](../ja_JP/FACTOR_API.md)

本指南说明当前 v1 配置契约与公开 Python 接口。新增因子从这里开始，再阅读[策略 API](STRATEGY_API.md)，将因子结果转换为组合决策。本文不承诺与所有未来版本兼容。

<!-- section:contract -->
## 1. 实现计算函数与参数校验器

```python
from kabuforge.api import FactorContext, FactorResult, FactorSpec


def compute_factor(spec: FactorSpec, context: FactorContext) -> FactorResult:
    ...


def validate_factor(spec: FactorSpec) -> None:
    ...
```

以上是接口签名，不是完整实现。不要求继承 `BaseFactor`。可信应用代码以实现 ID 和版本注册一个可调用对象。规格无效时，参数校验器应抛出异常；其返回值不会被使用。正常规划流程中，`ApplicationService.validate()` 会先运行已注册的校验器，计算结果必须为 `FactorResult`。

因子计算观测值或信号，不构建订单。网络访问、凭据处理、文件写入和缓存管理应放在计算逻辑之外。注册是信任边界，不是 Python 沙箱：只加载可信代码。

## 2. 定义版本化因子配置

可运行教程会生成下面这份完全一致的 `factor.json`：

```json
{
  "schema_version": "1.0",
  "id": "price_change",
  "version": "1",
  "kind": "factor",
  "implementation": {
    "id": "example.price_change",
    "version": "1",
    "parameters": {
      "periods": 1
    }
  },
  "data_requirements": [
    {
      "dataset": "prices",
      "fields": [
        "code",
        "date",
        "close"
      ]
    }
  ],
  "lookback": 2,
  "output": {
    "name": "price_change",
    "description": "Synthetic trailing price change",
    "unit": "return"
  }
}
```

| 字段 | 含义与当前边界 |
| --- | --- |
| `schema_version` | 配置格式版本，目前为 `"1.0"`。 |
| `id`、`version` | 这份因子配置的身份与版本；ID 也是策略公式使用的变量名。 |
| `implementation.id`、`implementation.version` | 已注册算法的精确身份；未知版本直接失败，不自动回退。它们与配置版本不同。 |
| `implementation.parameters` | 算法参数。通用 schema 只要求它是对象，具体语义由注册校验器检查。 |
| `data_requirements` | 声明需要的数据集与字段；不是自动下载器，也不是字段质量保证。 |
| `lookback` | 非负整数，含义由实现定义。本例要求 `periods + 1` 个观测值，而不是自然日；框架不会自动按该值截取数据。 |
| `output` | 输出名称、描述与可选单位；单位标签不会自动标准化数值。 |
| `metadata` | 可选说明信息；不得嵌入凭据或代码导入指令。 |

通用规范见 [factor.schema.json](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/schemas/factor.schema.json)，它拒绝未知的顶层字段。`FactorSpec.from_config()` 创建不可变规格，但**不能代替完整 JSON Schema 校验**。文件型运行应使用完成注册的服务调用 `validate(run_path)`；独立计算输入也应同时通过通用 schema 与参数校验器。

示例校验器要求 `periods` 为 1–252 的整数，拒绝布尔值和多余参数，并验证字段声明与回看长度。计算逻辑为“最后一个可见收盘价 ÷ 前 N 个观测位置的收盘价 − 1”。历史不足时保留缺失，不虚构缺少的交易日。

## 3. 只读取决策时点可见的数据

```python
prices = context.read("prices", fields=("code", "date", "close"))
universe = context.universe()
```

创建 `FactorContext` 时，提供明确带时区的 `decision_at`、数据集名称到 DataFrame 的映射，以及非空 `data_snapshot_hash`。每行输入都必须有带时区的 `available_at`；缺失或没有时区时拒绝读取。读取会过滤截止时刻之后的行；`asof` 只能早于或等于决策时刻。已有的 `date`、`asof_date`、`disclosed_date`、`data_end_date` 等日期列也会接受时间检查，但保留原始值。

`read(..., fields=...)` 仍会返回 `available_at`，每次读取都是深拷贝。`universe()` 选择最新可见的全局股票池快照，筛选 `in_universe == True`，并拒绝重复代码。该数据集需要 `asof_date`、`code`、`in_universe` 和 `available_at`。

声明的时间不等于真实历史可见性的证明。数据摄取阶段仍需核查可见时间、修订、公司行动和历史股票池成员。下载时间不能替代历史可见时间。向上下文传入快照哈希，也不会自动验证原始字节；本例在构建上下文前，会将文件字节与已校验运行绑定的哈希进行比对。

## 4. 返回 `FactorResult`

需要提供 `minimal`、`detail` 两张 DataFrame，以及 `summary` 映射。`minimal` 必须包含以下六列：

| 列名 | 含义与校验 |
| --- | --- |
| `code` | 本次结果中非空、唯一的证券标识。 |
| `factor_name` | 非空输出名称；新因子可以使用 `spec.id`。 |
| `factor_value` | 有限数值或明确的缺失值；拒绝无穷和无法解析的数值文本。 |
| `signal_date` | 信号日期；本例填写决策时刻对应的本地日期。 |
| `data_end_date` | 所使用数据的截止日期；本例没有历史数据时为缺失。 |
| `rebalance_date` | 兼容旧版的日期元数据，不是订单调度指令。 |

单个结果表达一次截面，而不是同一代码重复出现的多日期面板。日期列必须存在；构造器允许缺失日期，但拒绝非空且无法解析的日期。这种宽容不代表时间证据通过认证，实现仍应保留真实时间与日期含义。

本例返回 `FactorResult(..., factor_id=spec.id, binding_id=spec.id)`。`factor_id` 可用于检查 `factor_name`，`binding_id` 将结果绑定到配置中的因子 ID。独立绑定字段也支持必须保留旧 `factor_name` 的适配器。内置策略会检查绑定，自定义策略应保留等价检查。`from_legacy_dict()` / `to_legacy_dict()` 兼容原有 `minimal/detail/summary` 表示；结果访问器返回副本。

## 5. 在可信启动代码中注册

```python
from kabuforge.api import ApplicationService
from examples.extension_demo import compute_price_change, validate_price_change

app = ApplicationService()
app.register_factor(
    "example.price_change", "1", compute_price_change, validate_price_change,
)
```

此片段只注册因子。完整示例的 `build_service()` 同时注册因子和策略。配置只能选择获准 ID，不能要求任意 Python 导入、`eval` 或未登记实现。重复 ID/版本会失败。注册仅属于当前服务实例；另一个 CLI、GUI 或 MCP 进程不会自动发现示例，也不会自动复用该注册表。

## 6. 运行完整离线示例

在源码仓库根目录，使用 Python 3.12+：

```shell
python -m pip install -e .
python examples/extension_demo.py --out output/extension_demo
python -m unittest discover -s framework_v2/tests -p test_extension_example.py -v
```

输出目录必须是新目录，脚本不会覆盖已有目录。不指定 `--out` 时使用临时目录。[extension_demo.py](https://github.com/Siyuan-chat/KabuForge/blob/main/examples/extension_demo.py) 创建因子、策略、运行、快照和账户 JSON，校验配置引用图，计算因子，再调用 `ApplicationService.plan()`。

虚构证券 `SYN_A` 从 100 变为 110，`SYN_B` 从 100 变为 95；专门加入的一条未来 `SYN_B` 价格不可见。策略请求持有 `SYN_A`，单票仓位限制在规划前将原始权重从 1 降为 0.5。输出明确标记 `synthetic: true` 与 `orders_submitted: false`。本例不执行订单、不生成成交、不写执行账本、不评估历史收益，也不连接券商。

<!-- section:evidence -->
## 7. 验证、诊断与常见错误

[可执行教程测试](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/tests/test_extension_example.py)覆盖应用链路、命令行、不覆盖已有文件、未来行隔离、错误时间、错误参数、非法或重复价格、历史不足处理、注册失败、结果校验和决策状态语义。三语文档中的 JSON 块会与可执行配置工厂比对，防止示例漂移。

| 现象 | 检查方向 |
| --- | --- |
| 未知实现 | 在负责校验并运行配置的同一个服务中注册精确 ID/版本。 |
| 规格或回看长度错误 | 同时运行通用 schema 与实现校验器，不静默修正错误设置。 |
| 缺少 `available_at` 或时区 | 修复摄取证据，不为通过门禁而编造历史时间。 |
| 代码或观测重复 | 先明确数据粒度和修订处理，再计算因子。 |
| 因子值缺失 | 补足可见历史，或显式选择策略的 `reject` / `drop` 政策。 |
| 结果绑定不匹配 | 保持配置 ID 与 `binding_id` 一致；旧名称通过明确适配器保留。 |

缓存键绑定配置、算法身份、快照哈希、股票池身份和决策时点。`FactorSpec.cache_key()` 只计算身份，不读写缓存。`list_factors`、`describe_factor`、`validate_factor`、`analyze_factor` 是面向 agent 的目录、校验与诊断工具，不是每个因子必须实现的方法。分析提供覆盖率、缺失、分布、排名、分位和最大数据年龄，并报告 `research_readiness: NOT_EVALUATED`，不证明预测能力。

以代码为准：[因子契约](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/factors.py)、[应用服务](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/application.py)、[配置解析器](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/config.py)。继续阅读[策略 API](STRATEGY_API.md)和[研究方法](RESEARCH_METHODOLOGY.md)。
