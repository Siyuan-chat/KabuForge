# 安装、启动与运行约定

## 安装

支持 Windows 与 Python 3.12。请在发布副本根目录创建独立虚拟环境，并安装 GUI 依赖：

```powershell
py -3.12 -m venv .venv-gui
.\.venv-gui\Scripts\python.exe -m pip install --upgrade pip
.\.venv-gui\Scripts\python.exe -m pip install -r framework_v2/requirements-gui.txt
```

也可使用已安装完整依赖的 Python，并由启动器显式指定其路径。不要复用含有旧项目缓存、研究配置或密钥的环境。依赖安装需要网络连接，数据访问权限与软件安装相互独立。

## 启动

双击根目录 `Launch_KabuForge.bat`。启动器要求 PowerShell 7，并寻找能导入 PySide6、jsonschema、pandas 与 requests 的 Python 环境。若未找到，使用下列命令并将路径替换为实际解释器：

```powershell
pwsh -NoLogo -NoProfile -File framework_v2/launch_workbench.ps1 `
  -PythonPath .\.venv-gui\Scripts\python.exe `
  -Workspace .\output\kabuforge_workspace
```

工作区应为独立、可写的目录。软件将运行记录、下载文件、策略草稿与本地账本写入该工作区；不要把它设为源码目录或包含他人数据的共享目录。

## 手册与语言

工作台内按 F1 或选择“操作手册”阅读离线帮助。也可在浏览器打开：

- `framework_v2/docs/manual_zh_CN.html`
- `framework_v2/docs/manual_ja_JP.html`
- `framework_v2/docs/manual_en_US.html`

界面可切换中文、日文和英文，语言偏好与策略表单保存在本地工作区。手册仅说明软件操作，不构成投资建议或数据授权。

## 数据、模式和安全边界

演示模式仅使用合成数据。用户下载 J-Quants 数据前，应自行确认账户套餐、许可、保存期限和再分发限制；不得把任何源市场数据、API key、凭据导出物或本地缓存提交到仓库。

历史模拟与独立纸上模拟是研究模式。它们使用本地输入、固定规则和模拟 broker；没有真实订单路由。缺少完整交易日历、拆股处理、历史可见证据、执行报价或风险约束时，应停止对应研究结论，不以缺失值或当前下载时间代替证据。
