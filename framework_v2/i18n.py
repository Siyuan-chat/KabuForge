"""Display-only translations. Configuration keys and user input never change."""
from __future__ import annotations
from PySide6.QtWidgets import QLabel, QPushButton, QLineEdit, QComboBox, QTabWidget, QGroupBox, QListWidget
from PySide6.QtCore import QSignalBlocker

LANGUAGES = {"zh_CN": "简体中文", "ja_JP": "日本語", "en_US": "English"}
# Chinese source, Japanese, English. Stable source strings are also fallback text.
ROWS = [
 ("打开已保存策略","保存した戦略を開く","Open saved strategy"),
 ("选择已下载的数据","取得済みデータを選択","Choose downloaded data"),
 ("首页","ホーム","Home"), ("我的策略","マイ戦略","My strategies"),
 ("数据中心","データセンター","Data center"), ("回测结果","バックテスト結果","Backtest results"),
 ("纸上交易","ペーパートレード","Paper trading"), ("券商连接","証券会社接続","Broker connections"),
 ("运行记录","実行履歴","Run history"), ("操作手册","操作マニュアル","User guide"),
 ("工作台","ホーム","Home"), ("策略与因子","マイ戦略","My strategies"),
 ("数据与股票池","データセンター","Data center"), ("回测研究","バックテスト結果","Backtest results"),
 ("设置与帮助","操作マニュアル","User guide"),
 ("日本股票策略研究工作台","日本株戦略リサーチ","Japanese equity research"),
 ("本地研究 / 模拟\n真实交易未启用","ローカル研究 / シミュレーション\n実取引は無効","Local research / simulation\nLive trading disabled"),
 ("开始你的第一次研究","最初のリサーチを始める","Start your first research"),
 ("先体验，再连接自己的数据。所有策略与结果保存在本机。","まずデモを体験し、自分のデータを接続します。戦略と結果はローカルに保存されます。","Try the demo, then connect your data. Strategies and results stay on this computer."),
 ("1  体验离线演示","1  オフラインデモ","1  Try offline demo"),
 ("2  连接与下载数据","2  データを接続・取得","2  Connect and download"),
 ("3  创建我的策略","3  戦略を作成","3  Create a strategy"),
 ("创建合成演示","合成デモを作成","Create synthetic demo"),
 ("最近运行","最近の実行","Recent runs"),
 ("尚无运行。先体验无需 API key 的合成数据演示，或到数据中心连接 J-Quants。","実行履歴はありません。APIキー不要の合成デモ、またはデータセンターのJ-Quants接続から始めてください。","No runs yet. Start with synthetic data without an API key, or connect J-Quants in Data center."),
 ("演示使用虚构数据；不代表投资收益。真实数据下载后需选择价格研究模板。","デモは架空データです。投資収益を示しません。取得した実データには価格リサーチテンプレートを使用します。","Demo data is fictional, not investment performance. Use the price research template with downloaded market data."),
 ("策略名称","戦略名","Strategy name"), ("策略模板","戦略テンプレート","Template"),
 ("质量与趋势（合成演示）","クオリティとトレンド（合成デモ）","Quality and trend (synthetic demo)"),
 ("价格动量（下载数据）","価格モメンタム（取得データ）","Price momentum (downloaded data)"),
 ("数据来源","データソース","Data source"), ("合成演示","合成デモ","Synthetic demo"),
 ("下载数据","取得データ","Downloaded data"), ("持仓数量","保有銘柄数","Number of holdings"),
 ("调仓频率","リバランス頻度","Rebalance frequency"), ("每月","毎月","Monthly"),
 ("每周","毎週","Weekly"), ("每日","毎日","Daily"), ("等权","均等配分","Equal weight"),
 ("权重方式","配分方法","Weighting"), ("初始资金（JPY）","初期資金（JPY）","Initial cash (JPY)"),
 ("费用（单边，%）","手数料（片道、%）","Fee (one way, %)"),
 ("质量占比（%）","クオリティ比率（%）","Quality weight (%)"),
 ("动量观察期（交易日）","モメンタム期間（取引日）","Momentum lookback (sessions)"),
 ("用一句话辅助填写","文章から設定を補助","Fill fields from a sentence"),
 ("每月选5只股票，等权","毎月5銘柄を均等配分","Select 5 stocks monthly, equal weight"),
 ("解析到表单","フォームに反映","Parse into form"),
 ("本地解析只支持数量、频率、等权。其余条件请用表单设置；不会自动运行。","ローカル解析は銘柄数・頻度・均等配分に対応します。他の条件はフォームで設定してください。自動実行はしません。","Local parsing supports count, frequency and equal weight. Set other conditions in the form. Parsing never starts a run."),
 ("检查并创建策略","確認して戦略を作成","Review and create strategy"),
 ("开始回测","バックテスト開始","Start backtest"),
 ("高级配置与诊断","詳細設定と診断","Advanced configuration and diagnostics"),
 ("显示高级配置","詳細設定を表示","Show advanced configuration"),
 ("隐藏高级配置","詳細設定を隠す","Hide advanced configuration"),
 ("策略预览","戦略プレビュー","Strategy preview"),
 ("返回首页","ホームへ戻る","Back to Home"), ("帮助","ヘルプ","Help"),
 ("搜索章节或关键词…","章・キーワードを検索…","Search chapters or keywords…"),
 ("上一处","前を検索","Previous match"), ("下一处","次を検索","Next match"),
 ("目录","目次","Contents"), ("搜索结果","検索結果","Search results"),
 ("未找到匹配内容","一致する内容がありません","No matching content"),
 ("打开配置","設定を開く","Open configuration"), ("保存副本","コピーを保存","Save a copy"),
 ("选择目录","フォルダーを選択","Choose folder"), ("未打开配置","設定未選択","No configuration"),
 ("表单","フォーム","Form"), ("校验与依赖","検証と依存関係","Validation and dependencies"),
 ("高级 JSON","詳細 JSON","Advanced JSON"), ("浏览","参照","Browse"),
 ("选择 run","実行設定を選択","Choose run"), ("执行日历","実行カレンダー","Execution calendar"),
 ("执行报价","執行価格","Execution quotes"), ("决策时间（含时区）","判断日時（タイムゾーン付き）","Decision time (with timezone)"),
 ("执行时间（含时区）","執行日時（タイムゾーン付き）","Execution time (with timezone)"),
 ("运行数据与配置预检","データと設定を確認","Check data and configuration"),
 ("数据覆盖","データ範囲","Data coverage"), ("运行回测模拟","バックテスト実行","Run backtest simulation"),
 ("取消本任务","この処理を中止","Cancel this task"), ("打开结果","結果を開く","Open results"),
 ("比较运行","実行結果を比較","Compare runs"), ("净值 / 基准","純資産 / ベンチマーク","NAV / benchmark"),
 ("回撤","ドローダウン","Drawdown"), ("目标与风险","目標とリスク","Targets and risk"),
 ("交易","取引","Trades"), ("因子诊断","ファクター診断","Factor diagnostics"),
 ("运行比较","実行比較","Run comparison"), ("原始目标 → 风险 → 订单","元の目標 → リスク → 注文","Raw targets → risk → orders"),
 ("生成计划","計画を作成","Create plan"), ("执行独立模拟","独立シミュレーション実行","Run isolated simulation"),
 ("查询账本 / 恢复状态","台帳 / 復旧状態を確認","Query ledger / recovery status"),
 ("选择账本","台帳を選択","Choose ledger"), ("当前仓位","現在のポジション","Current positions"),
 ("订单","注文","Orders"), ("事件","イベント","Events"), ("成交","約定","Fills"),
 ("仓位","ポジション","Positions"), ("订单与阻断","注文とブロック","Orders and blockers"),
 ("恢复执行（依赖未就绪）","実行再開（準備未完了）","Resume execution (not ready)"),
 ("券商能力","証券会社の機能","Broker capabilities"),
 ("刷新本地能力说明","ローカル機能情報を更新","Refresh local capability information"),
 ("连接真实账户（本轮未启用）","実口座接続（無効）","Connect live account (disabled)"),
 ("任务记录","処理履歴","Task records"), ("打开结果文件","結果ファイルを開く","Open result file"),
 ("取消当前任务","現在の処理を中止","Cancel current task"),
 ("筛选表格…","テーブルを絞り込む…","Filter table…"), ("导出 CSV","CSV出力","Export CSV"),
 ("策略：尚未选择","戦略：未選択","Strategy: not selected"),
 ("账户：未选择","口座：未選択","Account: not selected"),
 ("数据截止：未预检","データ基準：未確認","Data cutoff: not checked"),
 ("回测 · 本地模拟","バックテスト · ローカル","Backtest · local simulation"),
 ("Paper · 独立模拟账户","Paper · 独立シミュレーション口座","Paper · isolated account"),
 ("FakeBroker · 协议模拟","FakeBroker · プロトコル模擬","FakeBroker · protocol simulation"),
 ("券商 · 仅能力查看","証券会社 · 機能表示のみ","Broker · capabilities only"),
 ("预检已失效 / 尚未预检；请重新检查当前输入。","入力が変更されたか未確認です。再度確認してください。","Inputs changed or have not been checked. Run the check again."),
 ("尚未预检。修改任一输入后，原预检自动失效。","未確認です。入力変更後は再確認が必要です。","Not checked. Changing any input invalidates the previous check."),
 ("● 未保存修改","● 未保存の変更","● Unsaved changes"), ("已保存 / 无修改","保存済み / 変更なし","Saved / unchanged"),
 ("费用、换手及方法限制将在完成后显示。","完了後に手数料・売買回転率・制約を表示します。","Fees, turnover and limitations appear after completion."),
 ("预检使用显式历史快照与 available_at；不会下载或改写本地数据。","詳細検証は履歴スナップショットとavailable_atを使用します。ダウンロードとは別の検証です。","Advanced checks use explicit snapshots and available_at. This is separate from downloading data."),
 ("表单与 JSON 使用同一模型；未知字段保留并报告，不会静默丢弃。","フォームとJSONは同じモデルを使用します。不明なフィールドは保持・報告します。","The form and JSON share one model. Unknown fields are retained and reported."),
 ("选择策略 → 数据预检 → 固定报价模拟 → 解释结果。所有运行保留配置快照。","戦略選択 → データ確認 → 固定価格シミュレーション → 結果確認。設定のスナップショットを保存します。","Select strategy → check data → simulate quotes → inspect results. Runs retain configuration snapshots."),
 ("模型：fictional_fixed_quote_matching_v1；费用取 run.fees。基准未提供时不绘制；该结果不代表真实成交。","固定価格の模擬約定モデルです。設定の手数料を適用します。ベンチマーク未指定時は表示せず、実約定を意味しません。","Fixed-quote simulation with configured fees. No benchmark is drawn unless supplied. These are not real fills."),
 ("独立模拟账户；计划、模拟执行与只读查询分别操作。不会使用现有生产 paper 账本。","独立した模擬口座です。計画・実行・照会を別々に操作します。既存の運用台帳は使用しません。","Isolated simulated account. Planning, execution and read-only queries are separate actions. Existing production ledgers are not used."),
 ("尚未查询账户。UNKNOWN 将阻止新执行并提示查询；界面没有重发入口。","口座未照会です。UNKNOWNは新規執行を停止します。照会が必要で、再送ボタンはありません。","Account not queried. UNKNOWN blocks new execution and requires reconciliation; there is no resend button."),
 ("连接不等于可交易。协议 mock、本机集成与真实账户状态分别显示。","接続と取引可能状態は異なります。模擬テスト・ローカル連携・実口座状態を分けて表示します。","Protocol mock, local integration and live-account verification are shown separately."),
 ("Excel：专用工作簿、插件、COM 端口及查询能力均需独立验证。当前不访问 Excel、凭证或真实账户。","Excelのブック・プラグイン・COM・照会機能は別途検証が必要です。現在はExcelや実口座へ接続しません。","Excel workbooks, plugins, COM and queries require separate verification. This page does not connect to Excel or live accounts."),
 ("每项任务有请求身份、不可变配置快照、PID、输出和退出码。取消仅处理本工作台持有的进程。","各処理の入力・設定スナップショット・PID・出力・終了コードを保存します。このアプリの処理だけを中止します。","Each task retains its request, configuration snapshot, PID, output and exit code. Cancellation affects only this workbench's processes."),
 ("运行后显示；不以演示曲线代替结果","実行後に表示します。仮の曲線は表示しません。","Shown after a run; no placeholder performance curve."),
 ("选择已保存的 run JSON","保存済み実行設定を選択","Select a saved run configuration"),
 ("执行日历 timeline.json（历史模拟）","実行カレンダー timeline.json","Execution calendar timeline.json"),
 ("独立报价 execution.json（计划 / 单步模拟）","執行価格 execution.json","Execution quotes execution.json"),
 ("选择 v2 journal.sqlite（只读）","v2 journal.sqliteを選択（読取専用）","Select v2 journal.sqlite (read only)"),
 ("选择事件查看完整明细","イベントを選択して詳細を表示","Select an event to see details"),
 ("真实查单 / 账户重同步及端到端恢复服务尚未完成；仅提供只读诊断","実注文照会・口座再同期・復旧サービスは未完成です。読取専用診断のみです。","Live order queries, account resync and full recovery are not implemented; read-only diagnostics only."),
 ("券商","証券会社","Broker"), ("协议模拟","プロトコル模擬","Protocol simulation"),
 ("本机集成","ローカル連携","Local integration"), ("真实账户","実口座","Live account"),
 ("查单 / 成交","注文 / 約定照会","Order / fill query"), ("依据","参照","Reference"),
 ("未验证 · 已禁用","未検証 · 無効","Unverified · disabled"),
 ("未验证 · 无默认连接","未検証 · 既定接続なし","Unverified · no default connection"),
 ("COM 端口未实现","COMポート未実装","COM port not implemented"),
 ("缺失 · 不可恢复","未実装 · 復旧不可","Unavailable · cannot recover"),
 ("仅映射 / 原始订单明细","マッピング / 生注文詳細のみ","Mapping / raw order details only"),
 ("期次","回","Period"), ("代码","銘柄コード","Code"), ("原始权重","元の比率","Raw weight"),
 ("允许权重","許容比率","Allowed weight"), ("方向","売買区分","Side"), ("股数","株数","Quantity"),
 ("原因","理由","Reason"), ("因子","ファクター","Factor"), ("策略净值","戦略純資産","Strategy NAV"),
 ("策略回撤","戦略ドローダウン","Strategy drawdown"), ("维度","項目","Dimension"),
 ("当前","現在","Current"), ("对比","比較","Comparison"), ("一致","一致","Match"),
]
TEXT = {zh: {"zh_CN": zh, "ja_JP": ja, "en_US": en} for zh, ja, en in ROWS}
for key,zh,ja,en in [
    ("job_id","任务编号","処理ID","Task ID"),("action","操作","操作","Action"),("status","状态","状態","Status"),
    ("started_at","开始时间","開始時刻","Started"),("exit_code","退出码","終了コード","Exit code"),("output_dir","结果位置","保存先","Output folder"),
    ("code","证券代码","銘柄コード","Security code"),("date","日期","日付","Date"),("side","方向","売買","Side"),
    ("quantity","数量","数量","Quantity"),("price","价格","価格","Price"),("fee","费用","手数料","Fee"),
    ("signal_date","信号日期","シグナル日","Signal date"),("dataset","数据集","データセット","Dataset"),
    ("coverage","覆盖情况","カバレッジ","Coverage"),("freshness","最新已知时间","最新既知時刻","Latest known time"),
    ("account_id","账户","口座","Account"),("buy","买入","買い","Buy"),("sell","卖出","売り","Sell"),
    ("COMPLETED","完成","完了","Completed"),("FAILED","失败","失敗","Failed"),("CANCELED","取消","中止","Cancelled"),
    ("RUNNING","运行中","実行中","Running"),("guided_demo","创建演示策略","デモ戦略作成","Create demo strategy"),
    ("price_research","价格研究","価格リサーチ","Price research"),("preflight","预检","事前検証","Preflight"),
    ("history","回测","バックテスト","Backtest"),("simulate","纸上模拟","ペーパー模擬","Paper simulation"),
    ("plan","生成计划","計画作成","Plan"),("journal","查询账本","台帳照会","Query ledger"),
]: TEXT[key]={"zh_CN":zh,"ja_JP":ja,"en_US":en}

def tr(text, language="zh_CN"):
    return TEXT.get(text, {}).get(language, text)

class Translator:
    def __init__(self, language="zh_CN"):
        self.language = language
        self._seen = {}  # Qt object keys avoid recycled Python ids.

    def _render(self, obj, prop, value, setter):
        key = (obj, prop)
        source, previous = self._seen.get(key, (value, None))
        if value != previous:
            source = value
        rendered = tr(source, self.language)
        setter(rendered)
        self._seen[key] = (source, rendered)

    def apply(self, root):
        for obj in [root, *root.findChildren(QLabel), *root.findChildren(QPushButton),
                    *root.findChildren(QLineEdit), *root.findChildren(QComboBox),
                    *root.findChildren(QTabWidget), *root.findChildren(QGroupBox), *root.findChildren(QListWidget)]:
            ancestor=obj; owned=False
            while ancestor is not None and ancestor is not root:
                if ancestor.property("ownTranslation"): owned=True; break
                ancestor=ancestor.parent()
            if owned:
                continue
            if isinstance(obj, (QLabel, QPushButton)):
                self._render(obj, "text", obj.text(), obj.setText)
            if isinstance(obj, QLineEdit):
                self._render(obj, "placeholder", obj.placeholderText(), obj.setPlaceholderText)
            if isinstance(obj, QGroupBox):
                self._render(obj, "title", obj.title(), obj.setTitle)
            if isinstance(obj, (QComboBox, QTabWidget, QListWidget)):
                blocker = QSignalBlocker(obj)
                for i in range(obj.count()):
                    getter = obj.itemText if isinstance(obj,QComboBox) else obj.tabText if isinstance(obj,QTabWidget) else lambda n:obj.item(n).text()
                    setter = obj.setItemText if isinstance(obj,QComboBox) else obj.setTabText if isinstance(obj,QTabWidget) else lambda n,t:obj.item(n).setText(t)
                    self._render(obj, str(i), getter(i), lambda t,n=i:setter(n,t))
                del blocker
            if hasattr(obj,"toolTip"):
                self._render(obj,"tooltip",obj.toolTip(),obj.setToolTip)
