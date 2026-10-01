---
doc_id: research_methodology
version: 1
locale: zh_CN
---

# 研究方法

<!-- section:contract -->
## 合约

研究输入必须声明决策时间和快照标识。`check_point_in_time` 与 `check_lookahead` 用 `available_at` 检查可见性；晚于决策时间的行会被计数，必须由时点上下文门控。缺少可用时间戳的数据集在此检查中无效。

`check_lookahead` 仅是 available-at 门控，不是对来源、供应商时间、历史修订、幸存者偏差、公司行动、股票池构建或经济有效性的完整科学认证。

<!-- section:evidence -->
## 证据

诊断返回 `decision_at`、每数据集行数、缺失时间戳、未来行、可见行、有效性和 `future_rows_require_gate`。因子诊断只描述给定结果，不能证明样本外表现或可投资性。
