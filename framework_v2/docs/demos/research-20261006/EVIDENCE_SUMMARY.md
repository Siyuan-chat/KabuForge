# Reference GUI evidence / GUI 参考证据 / GUI 参考証跡

These 219 screenshots were captured from the public-candidate source checkout running the actual Qt workbench in Chinese, Japanese and English. They are source-build captures, not screenshots from an installed wheel. The public media manifest SHA256 is `ffed7b0325d0a817e67acc4e81e50a1d39d964090ef969b4bc881d5fecc96ae6`. They document workflows using the owner’s real historical J-Quants cache and are permitted for public teaching; original market files, detailed reports, model artifacts and Paper ledgers are not included. Installed-distribution acceptance must be supported by a record bound to the actual wheel and runtime; these images alone cannot establish it.

这 219 张截图由公开候选源码检出后实际运行 Qt 工作台捕获，分别以中文、日文和英文渲染；它们不是安装 wheel 后的截图。公开 media manifest SHA256 为 `ffed7b0325d0a817e67acc4e81e50a1d39d964090ef969b4bc881d5fecc96ae6`。截图展示所有者真实 J-Quants 历史缓存的教学流程，已获准公开；原始行情、完整报告、模型文件及 Paper 账本不随包分发。安装包验收须由与实际构建 wheel/runtime 身份绑定的记录证明，不能凭这些截图推断。

219枚は公開候補ソース checkout から実際に Qt workbench を実行し、中国語・日本語・英語で撮影した画像です。インストール済み wheel の画面ではありません。公開 media manifest SHA256 は `ffed7b0325d0a817e67acc4e81e50a1d39d964090ef969b4bc881d5fecc96ae6` です。所有者の実 J-Quants 履歴 cache を使った教育用フローで、画像公開は承認済みです。元市場データ、完全 report、model artifact、Paper 台帳は同梱しません。配布物の受け入れは、実際の wheel/runtime identity に結び付いた別記録で確認します。これらの画像だけでは証明できません。

| Reference input / 参考输入 / 参照入力 | Identity |
|---|---|
| Securities | 4502, 6758, 8306 |
| Requested range | 2017-01-01 to 2022-12-31 |
| Observed common dates | 2017-01-04 to 2022-12-30; 1,464 dates |
| Frozen bars | 4,392 rows; original raw prices; no dividend cash model |
| Cache/MA GUI freeze manifest SHA256 | `273e54f93681ed0144a80b68cd877d144b1a70f1805b75e1f58664e026e54cdc` |
| Research/report manifest SHA256 | `c245051c1a33cabee8043b23a5f170bc84b5c2ea8e4351b6c6f781291f9cd545` |
| Manifest relationship | Byte-distinct manifests select the same 4,392 raw-bar rows; identities are not interchangeable. |
| Public media manifest SHA256 | `ffed7b0325d0a817e67acc4e81e50a1d39d964090ef969b4bc881d5fecc96ae6` |
| Benchmark | Actual TOPIX closing price index, excluding dividends; exact NAV-date matching |

The five source-GUI courses cover cache import/freeze, indicators and MA, factor evaluation, factor/model/engine strategies, historical Paper replay, and broker configuration/local mapping. The cache workflow has five checkpoints: explicit file, codes/date/basis, coverage/source identity, duplicate/halt policy, and freeze/reverification. Its receipt recorded 8,172 selected rows before deduplication, removed 3,777 fully identical rows, excluded only three verified 2020-10-01 TSE-halt placeholders, and retained 4,392 rows over 1,464 dates. The report has 19 dark figures: chart 03 is drawdown and chart 07 is the actual TOPIX closing-price index, matched only on exact NAV dates; it excludes dividends and does not fill gaps. The separate sensitivity panel displays three fixed cases each for Native MA, TA-Lib MA, and price momentum. Across nine cases, full financial paths match independent accounting. The 0.2% fee reruns recalculate quantities; the +1 observed-session diagnostic holds baseline quantities fixed. Monetary values in the course tables are displayed to two decimals. No scenario is selected as a winner.

In your own workspace, inspect each job’s request, launch, result, exit, and stdout/stderr records. For cache import, verify the selected file, explicit code/date/basis settings, dedup/halt counts, retained coverage, and final manifest SHA. For research runs, confirm the report’s bound manifest and source hash before reading performance. The source screenshots use two byte-distinct manifest identities shown above for different workflows; both select the same reference raw bars. Your own data produces its own identities and results. `media_manifest.json` contains image paths and hashes, not market data or account credentials. Detailed source receipts, raw bars, report JSON, model artifacts, and Paper ledgers remain outside this public summary.

Historical availability is unverified: these are RESEARCH-ONLY teaching runs with `pit_guarantee=false`, not strict PIT, unseen OOS or PAPER-READY evidence. Historical Paper is replay, not fresh forward observation. Broker mapping is offline; the reference missing-credential read-only check made zero network calls. A real broker terminal connection was not verified, and live submission is disabled. The public package defaults to Regime Off and does not include the private state-machine bridge. Historical Regime charts require qualified evidence in the selected report; missing evidence remains unavailable.
