# 三语操作演示

采用本地已有的 2026-09-30 三语操作录制，媒体文件保持原样。下载仓库后打开 [演示总览](demos/index.html)，或直接查看下列 GIF。

- [中文截图集](demos/zh_CN/index.html) · [中文 GIF](demos/zh_CN/workflow.gif)
- [日本語スクリーンショット](demos/ja_JP/index.html) · [日本語 GIF](demos/ja_JP/workflow.gif)
- [English screenshots](demos/en_US/index.html) · [English GIF](demos/en_US/workflow.gif)

这些录制来自既有本地研究流程，含历史曲线与本机示例路径；不是本次公开因子的业绩演示。GIF 压缩等待时间，保留实际界面画面；录制中的失败记录也未抹去。原始数据、私有因子源码、运行配置与账本不发布。源码的可复现验证使用下面的独立合成演示。

媒体 SHA256 见 [清单](demos/media_manifest.json)。HTML 在 GitHub 中显示源码，下载后可在浏览器浏览；GIF 可直接查看。

## 合成演示与验收范围

本演示只验证公开发布软件的可安装性、配置读取、公开因子接线、PIT 字段校验、订单规划、本地 SQLite 账本与确定性模拟撮合。它不读取真实 J-Quants/JPX 数据，不调用券商，不评价因子有效性，也不产生实盘或纸面投资建议。

在发布副本根目录、已激活或明确指定 Python 3.12 环境后运行：

```powershell
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli demo --out output/demo
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli validate output/demo/paper.json
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli history output/demo/backtest.json --timeline output/demo/timeline.json --out output/history
```

若使用其他解释器，请将前缀替换为对应 Python 可执行文件。`demo` 会新建示例配置和合成输入；不可把已有真实研究目录作为 `--out`。`validate` 应在不修改示例的情况下完成模式与字段校验。`history` 使用显式时间线进行连续本地模拟，并在 `output/history` 写入报告与 SQLite 账本。

可补充执行以下只读诊断：

```powershell
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli factors
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli doctor
.\.venv-gui\Scripts\python.exe -m unittest discover -s framework_v2/tests -v
```

验收应记录解释器版本、依赖安装结果、命令、退出码和新建输出路径。截图或离屏 Qt 验收只说明控件在该环境可渲染，不能替代原生桌面交互、真实 API、Windows 凭据管理器、Excel COM、券商连接、数据许可或投资策略验证。

发布后的可重复结论仅限“软件在指定环境中完成合成演示”。任何涉及历史业绩、PIT 完整性、交易成本、容量、风险、实际执行或未来收益的结论，均需要独立数据、审计与研究验证，不能从本演示推得。
