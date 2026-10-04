---
doc_id: release_process
version: 1
locale: zh_CN
---

# 发行流程

<!-- section:contract -->
## 合约

公开正式版为 `0.1.1`，包名 `kabuforge`，GitHub 正式发行标签为 `v0.1.1`。公开因子及 runtime 源码固定于既有已公开基底；私有本地工作区是独立发行物，不作为公开因子打包输入。须通过测试、独立 wheel 安装、源码/wheel/sdist 边界审计和 CI 后发布。发行不授予交易权限。

<!-- section:evidence -->
## 证据

`public_source_manifest.json` 固定规范化源码哈希；`tools/check_public_distribution.py` 拒绝来源变更、根级私有 runtime、生成状态与凭证。发行附件包括公开 wheel、源码包及校验和。GitHub CI 检查 Windows/Ubuntu、API/CLI/MCP 和文档一致性。R3 默认不注册，选用时显示的预留入口仍禁用。
