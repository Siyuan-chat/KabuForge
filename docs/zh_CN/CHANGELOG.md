---
doc_id: changelog
version: 1
locale: zh_CN
---

# 变更日志

<!-- section:contract -->
## 合约

## 0.1.0-rc.1

引入本地 CLI 与受限 MCP 适配器、类型化因子和策略注册表、本地 Agent 审计回执、默认 R0/R1 目录、显式 R2 paper 开关及保留但禁用的 R3 审批/订单接口；公开 RC 将公开包与私有本地工作区分离，并固定公开因子源码身份。

<!-- section:evidence -->
## 证据

已知限制：Agent 无真实券商提交；`--expose-reserved-external` 只暴露禁用 stub；任务为进程内 daemon 线程；重启将排队/运行任务转为带 `KF_JOB_INTERRUPTED` 的 `FAILED`；没有自动恢复/重放；前视检查仅为时间戳门控。
