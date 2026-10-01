---
doc_id: adr_agent_boundary
version: 1
locale: zh_CN
---

# Agent 应用边界

<!-- section:contract -->
## 决议

Agent 通过经验证的命令和工作区内资源操作共享应用服务。禁止任意 Python 导入、文件系统越界与券商凭据输入。默认 MCP 注册 R0/R1。R2 须明确启用 paper，并留存持久化幂等凭证。在可信审批机构与券商传输接入之前，R3 扩展保持禁用。

<!-- section:evidence -->
## 影响

可展示禁用的 R3 schema 供集成设计使用；展示接口不授予下单权限。订单接口参考：[Alpaca 官方 MCP](https://github.com/alpacahq/alpaca-mcp-server)。研究可用评级与真实券商认证仍属独立验收。
