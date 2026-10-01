---
doc_id: factor_api
version: 1
locale: zh_CN
---

# 因子 API

<!-- section:contract -->
## 合约

因子以实现 ID 和版本从白名单注册表选择。实现接收 `FactorSpec` 与 `FactorContext`，必须返回 `FactorResult`；登记校验器会先校验规格。禁止动态导入、求值和未校验实现选择。

缓存键绑定实现参数、数据快照哈希、股票池标识和决策时点，因此命中仍受声明研究上下文约束，而非仅按因子名称。

<!-- section:evidence -->
## 证据

`list_factors`、`describe_factor`、`validate_factor` 与 `analyze_factor` 提供目录、校验与描述性诊断。分析报告覆盖率、缺失、分布、排名、分位和最大数据年龄，并报告 `research_readiness: NOT_EVALUATED`。
