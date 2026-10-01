---
doc_id: readme
version: 1
locale: zh_CN
---

# KabuForge 本地版 v0.1.0-rc.1

<!-- section:contract -->
## 合约

KabuForge 是本地日股研究与模拟软件包：校验声明式运行文件、构建因子和策略决策、生成券商中立订单意图，并运行本地回测、纸面或假券商模拟；绝不提交真实订单。安装本地检出并使用 CLI：

```shell
pip install -e .
kabuforge demo --out output/new_demo
kabuforge mcp --workspace output/agent_workspace
```

公开 RC 保留既有已公开因子实现；私有工作区实现、账户状态、缓存和凭证不进入此发行物。旧 GUI 的说明继续由既有手册维护。

<!-- section:evidence -->
## 证据

`kabuforge` 提供 `doctor`、`factors`、`strategies`、`demo`、`backtest`、`paper` 与 `mcp`。运行模式必须匹配 `backtest` 或 `paper`；`demo` 只产生本地合成输出。当前版本为 `0.1.0rc1`，正式 v0.1.0 尚需独立公共实现与发行审计。
