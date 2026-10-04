---
doc_id: changelog
version: 1
locale: zh_CN
---

# 变更日志

## 0.1.1 — 正式发布

将已验证的 v0.1.0-rc.2 代码提升为 AGPL-3.0-only 正式版。
软件包、CLI 与 MCP 版本统一为 0.1.1，API 和依赖保持一致。
既有 MIT 发行物保留原许可证。

## 0.1.0-rc.2 候选：当前源码许可与 GitHub 导航

项目自有材料从提交 `3bdbb7e1b68de53fcb243abb92cd851801dcb7be` 起采用 AGPL-3.0-only。
NOTICE / PROJECT_LICENSING.md 保留原 MIT 通知和外部贡献来源。
既有 v0.1.0-rc.1、v0.1.0 Release、tag、wheel/sdist 附件及校验和保持 MIT 且不变。
该历史候选的包版本为 0.1.0rc2，版本排序低于 0.1.0。
运行时依赖与 API 不变。更新包括三语能力证据、研究边界、引用、导航、社区表单
和文档检查。字标已改用固定来源的 OFL Noto Sans 转曲，铁砧保持原样；字体软件
仍按 OFL 授权且不打包。

<!-- section:contract -->
## 合约

## 0.1.0-rc.1

引入本地 CLI 与受限 MCP 适配器、类型化因子和策略注册表、本地 Agent 审计回执、默认 R0/R1 目录、显式 R2 paper 开关及保留但禁用的 R3 审批/订单接口；公开 RC 将公开包与私有本地工作区分离，并固定公开因子源码身份。

<!-- section:evidence -->
## 证据

已知限制：Agent 无真实券商提交；`--expose-reserved-external` 只暴露禁用 stub；任务为进程内 daemon 线程；重启将排队/运行任务转为带 `KF_JOB_INTERRUPTED` 的 `FAILED`；没有自动恢复/重放；前视检查仅为时间戳门控。
