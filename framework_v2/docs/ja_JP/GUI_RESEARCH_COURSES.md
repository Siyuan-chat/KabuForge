---
doc_id: gui_research_courses
version: 1
locale: ja_JP
---

# KabuForge GUI 研究コース（実データ・ローカル市場データ）

この5コースは公開候補ソース checkout から Qt GUI を実行し、中国語・日本語・英語で実際に描画した操作記録です。219枚は公開ソースの GUI capture であり、wheel をインストールした画面ではありません。clean wheel のインストールや optional runtime の受け入れを証明しません。公開版は Regime 既定 Off、private state-machine bridge を含みません。この参考 report の Chart 19 は Off/unavailable、trace 0 件で、適格な内部 state 軌跡ではありません。CSV/Parquet/manifest は利用者が明示選択します。市場データや口座データは同梱しません。

5つの手順は同じ選択済みローカル J-Quants 日足を使いますが、source run ごとに別の完了 manifest が結び付いています。実履歴の計算は当時の可視性を証明しません。各 run は **RESEARCH-ONLY、`pit_guarantee=false`** です。Historical Paper は過去データの研究 replay であり forward simulation ではありません。broker mapping はローカルで、端末接続・submit・cancel を行いません。

<!-- section:contract -->
## 共通の入力 identity と固定値

3言語で同一の照合値を使います。パスと SHA は identity のみです。原データ、日次明細、口座データ、完全な report はローカルの私有 evidence に保存します。

```text
codes=4502,6758,8306
reference_window=2017-01-01..2022-12-31
reference_observed_window=2017-01-04..2022-12-30
input=explicit user-selected local CSV/Parquet/snapshot/completed manifest
bundled_market_data=none
cache_ma_gui_manifest_sha256=from_local_cache_or_MA_receipt
reference_research_manifest_sha256=from_selected_research_run_receipt
public_media_manifest=docs/demos/research-20261006/media_manifest.json
public_media_manifest_sha256=from_current_acceptance_receipt
manifest_relation=distinct_bytes; same_4392_selected_raw_rows
price_basis=raw
MA_fast_slow=20/60
momentum_window=20
factor_windows=20/60; direction=positive; weights=0.5/0.5
factor_label=execution_open_to_fifth_observed_session_open
minimum_cross_section=3; quantiles=3
portfolio=top2; rebalance=monthly; initial_cash_JPY=2000000; one_way_fee=0.001
model_split=train=2017-2019; validation=2020; historical_test=2021-2022; seed=42
benchmark=local TOPIX price index; price-only; no dividends
pit_guarantee=false; status=RESEARCH-ONLY
```

銘柄と期間は現在の執行条件・企業行動制約に基づいて事前固定しており、収益で選んでいません。凍結時は完全一致する重複のみを明示的に統合し、JPX の公表で確認された 2020-10-01 の全日取引停止空データだけを除外します。他の競合・欠損は削除も補完も捏造もしません。TOPIX は実際のローカル価格指数で、NAV 評価日と厳密に揃えます。欠損をゼロ/前値で埋めず、配当も加えません。
cache import/MA freeze と後続の research run は、同じ4,392件の raw-bar 行を選択しても byte の異なる manifest に結び付く場合があります。各 run の cache/job/report receipt から実際の manifest SHA を確認し、別操作の hash を流用しないでください。撮影した参照例の正確な identity は、同梱 docs の `EVIDENCE_SUMMARY.md` に記載します。画像 index は現在の `media_manifest.json` と受け入れ receipt で確認します。

## 開始と市場データの固定

公開ソース workbench を起動し言語を選びます。左 nav は Home、My Strategies、Data Center、Backtest Results、Paper Trading、Broker Connections、Run History です。「Data Center → Local market cache · Offline research input」で5段階を確認します。(1) ファイルまたは完了済み manifest を明示選択、(2) 銘柄・日付・研究価格口径を指定、(3) coverage・source identity・hash を確認、(4) 完全一致 duplicate と確認済み halt の明示 policy を確認、(5) validate、freeze、再検証して新 manifest を作成します。参考 cache receipt では重複前 8,172 行から完全一致行 3,777 件を除外し、2020-10-01 全日停止 placeholder の3行だけを除いて、1,464日・4,392行を保持しました。競合行やその他欠損は fail closed で、削除/補完しません。言語変更で入力 identity は変わりません。

本コースはローカルに既存する J-Quants 履歴を利用します。Data Center の接続テスト/ダウンロードはユーザーが明示的に行う別操作で、コースの前提ではありません。本コースは credential を読まず、ネットワーク要求もしません。別途ダウンロードしても download date は過去の `available_at` を証明しません。

公開証拠サマリーには Qt capture の出所と identity を記し、元 Parquet や完全 manifest は含めません。各 run の receipt で input SHA を確認してください。参考観測窓は2017-01-04～2022-12-30、共通観測日1,464日です。

cache task ごとに request、launch、result、exit、stdout/stderr を保持・確認します。選択内容、duplicate/halt 件数、保持 coverage、最終 manifest SHA を照合してください。Run History からローカル evidence を確認します。画像だけでは receipt の代わりになりません。

![ローカル市場データの選択](../demos/research-20261006/ja_JP/cache-selection.png) ![検証・凍結後の入力](../demos/research-20261006/ja_JP/cache-frozen.png)

メインウィンドウの「操作マニュアル」からコース全文を検索できます。「Demo 1」で最初のコースへ移動し、「broker」で検索して一致項目を開くと Demo 5 に移動します。マニュアルの画像とリンクはローカル資源で、検索や言語切替で研究タスクは起動しません。

![Demo 1 の手册ページ](../demos/research-20261006/ja_JP/manual-course-demo-1.png) ![broker 検索から Demo 5 へ](../demos/research-20261006/ja_JP/manual-search-broker.png)

## Demo 1：価格モメンタム、MA 20/60、テクニカル指標

「My Strategies」で新しい研究戦略を作り、「Price momentum (downloaded data)」テンプレート、凍結入力、20日モメンタム、月次、保有2、資金 2,000,000 JPY、片道0.1%を指定します。別の信号テンプレートとして「MA crossover (prior close / next open)」を選び、短期/長期を20/60にします。NAVを見てから窓を変えず、事前チェックを通して実行します。

シグナルは前の観測日以前の終値、数量は前終値で固定、次の観測日の実始値で約定します。同日売りを買いより先に処理します。寄付きギャップ等で現金不足なら数量を再計算せず注文全体をスキップし、NAV は未調整終値で評価します。Native と TA-Lib の MA が同じ凍結 recipe を使うと金融結果は同じです。指標 provider は戦略計算を変更しません。価格モメンタム参照は1,464観測日、約定注文161件、スキップ22件です。ただし入力、recipe、report identity が完全一致する場合にのみ照合してください。注文数は完了取引数ではありません。

「Backtest Results」で input SHA、期間、保有/現金、実約定、スキップ理由、費用を確認します。価格図では前日シグナル、実際の始値約定、未約定スキップを分けて読みます。価格図の約定マーカーはシグナル価格ではありません。配当、スリッページ、市場インパクト、単元株制約は含みません。PIT は未認証で、新規 OOS や PAPER-READY と呼べません。

![Native MA の設定](../demos/research-20261006/ja_JP/ma-native-configured.png) ![Native MA 結果](../demos/research-20261006/ja_JP/ma-native-results.png) ![TA-Lib MA の設定](../demos/research-20261006/ja_JP/ma-talib-configured.png) ![TA-Lib MA 結果](../demos/research-20261006/ja_JP/ma-talib-results.png)

別途「Data Center → Technical indicator research」で同じ manifest と一銘柄を選択し、receipt が利用可能と示す TA-Lib または pandas-ta を実行します。SMA20、RSI14、ATR14、MACD12/26/9 を指定し、「Calculate and view indicators」を押します。価格/SMA（JPY/株）、RSI（0–100固定）、MACD line/signal/histogram、ATR（JPY/株）を別々に読みます。warm-up 欠損は空欄、線は欠損箇所で途切れ、補間しません。ATR は入力と同じ価格口径の完全な OHLC を使用します。pandas-ta receipt には provider 実装の既定 warm-up SMA seed が記録されます。2 provider の版や初期化による小差は receipt に記録されます。Native は MA 戦略経路であり、RSI/MACD/ATR の indicator provider ではありません。指標から自動で注文は作られません。

![TA-Lib 指標設定](../demos/research-20261006/ja_JP/indicator-talib-controls.png) ![TA-Lib 価格と SMA](../demos/research-20261006/ja_JP/indicator-talib-price-sma.png) ![TA-Lib RSI](../demos/research-20261006/ja_JP/indicator-talib-rsi.png) ![TA-Lib MACD](../demos/research-20261006/ja_JP/indicator-talib-macd.png) ![TA-Lib ATR](../demos/research-20261006/ja_JP/indicator-talib-atr.png)

![pandas-ta 設定](../demos/research-20261006/ja_JP/indicator-pandas_ta-controls.png) ![pandas-ta 価格と SMA](../demos/research-20261006/ja_JP/indicator-pandas_ta-price-sma.png) ![pandas-ta RSI](../demos/research-20261006/ja_JP/indicator-pandas_ta-rsi.png) ![pandas-ta MACD](../demos/research-20261006/ja_JP/indicator-pandas_ta-macd.png) ![pandas-ta ATR](../demos/research-20261006/ja_JP/indicator-pandas_ta-atr.png)

失敗時は銘柄の一意性、OHLC 完全性、整数 period、warm-up 件数と隔離 runtime receipt を確認します。オプション依存を GUI の NumPy/pandas 環境へ移さないでください。再実行は新しい run とし、失敗 evidence を保持します。

## Demo 2：因子 feature と独立評価

「Data Center → Factor diagnostics · RESEARCH-ONLY」で同じ manifest を選びます。20日/60日モメンタム、正方向各0.5、rank normalization、min cross-section 3、3分位、5観測日の forward label を固定してから実行します。

![因子ワークベンチ](../demos/research-20261006/ja_JP/factor-workbench.png) ![feature と recipe](../demos/research-20261006/ja_JP/factor-input-and-recipe.png)

最初に feature/recipe を確認します。`feature_rows` は signal date の D-1 終値までから計算し、評価 label と別ファイルです。label は execution open から5番目の後続観測日 open までの単純収益で、evaluation panel 専用です。末尾の label 不足行は欠損として残し、戦略予測へ入りません。日次 IC/Rank IC、横断面 sample/coverage、分位収益、分位構成銘柄の turnover、因子相関、年度別の記述統計を確認します。constant、欠損、無効日には理由が出ます。同値を code 順に分桶しても情報量はありません。3銘柄では最大3分位です。重複 label は独立サンプルを増やしません。ICIR は mean/std の記述量であり、未校正の統計推論ではありません。

forward label、分位収益、evaluation panel を戦略入力にしないでください。この期間から方向や重みを選びません。再現には `contract.json`、`receipt.json`、`report.json` と run のログを保持します。共同日付や完全性が欠ける場合は、銘柄を捨てて coverage を見かけ上埋めず、receipt の理由を調べます。

![IC / Rank IC](../demos/research-20261006/ja_JP/factor-ic-rank-ic.png) ![分位 return](../demos/research-20261006/ja_JP/factor-quantiles.png) ![coverage](../demos/research-20261006/ja_JP/factor-coverage.png) ![銘柄構成 turnover](../demos/research-20261006/ja_JP/factor-turnover.png) ![因子相関](../demos/research-20261006/ja_JP/factor-correlation.png) ![年次記述統計](../demos/research-20261006/ja_JP/factor-observed-years.png)

## Demo 3：ポートフォリオ、時間分割モデル、エンジン候補

「Data Center → Research Studio」の「Strategy」タブで score source を明示します。label を含まない `factor_feature_rows`、または確定済みモデル `predictions` を選択し、バイト SHA を確認します。evaluation/forward-label ファイルは選びません。保有2、月次、2,000,000 JPY、片道0.1%、min cross-section 3、20/60正方向各0.5を維持します。実行後は signal date、execution date、fill/skip と日次 NAV を見ます。

![20/60 因子合成設定](../demos/research-20261006/ja_JP/studio-factor-composite-controls.png) ![因子合成結果](../demos/research-20261006/ja_JP/studio-factor-composite-results.png)

「Models」タブで凍結因子 run を選択し、LightGBM と CatBoost の両方を実行します。固定 split は train 2017–2019、validation 2020、historical diagnostics 2021–2022、seed 42。label end date によって境界を purge します。ランダム split、自動 tuning、自動モデル選択はありません。train fit predictions は診断用です。戦略 predictions から train 期間を除外し、モデル利用可能時刻が label cutoff より後であることを確認します。2021–2022 は既知の歴史で、新規 OOS ではありません。split 件数、purge、欠損理由、model/prediction SHA を保存します。

「Engines」タブで同一入力と frozen order recipe の Native、VectorBT、Backtrader を個別に確認します。各エンジンは固定数量を実行し、Native NAV をコピーしません。daily account tolerance と execution stream equality は別の状態です。fill の日付、side、qty、実始値、fee、skip を比較し、現金/long-only semantics の差はそのまま残します。期末現金が近くても約定が違えば一致とは言えません。Backtrader next-bar market event は証券会社約定ではありません。

![両モデル設定](../demos/research-20261006/ja_JP/studio-both-models-controls.png) ![LightGBM score 結果](../demos/research-20261006/ja_JP/studio-lightgbm-score-results.png) ![CatBoost 設定](../demos/research-20261006/ja_JP/studio-catboost-score-controls.png) ![CatBoost score 結果](../demos/research-20261006/ja_JP/studio-catboost-score-results.png) ![両モデル結果](../demos/research-20261006/ja_JP/studio-both-models-results.png) ![両モデルの残りの図](../demos/research-20261006/ja_JP/studio-both-models-remaining-results.png)

![engine 設定](../demos/research-20261006/ja_JP/studio-engines-20-60-controls.png) ![engine 概要](../demos/research-20261006/ja_JP/studio-engines-20-60-results.png) ![engine の残りの図](../demos/research-20261006/ja_JP/studio-engines-20-60-remaining-results.png)

まず account path、order schedule、費用、report/source hash を確認してからチャートを見ます。実 TOPIX 価格指数は配当を含まず、NAV 日に完全一致した場合のみ相対指標を評価します。欠日は利用不可です。現在の dashboard は全19図（全体15図、銘柄別価格/執行3図、Regime 1図）です。この参考 report の Regime 図は Off/unavailable、trace 0 件で、適格な state 軌跡を含みません。手数料・執行遅延の感度分析は結果ページの独立パネルで実行し、19図には含めません。全結果 RESEARCH-ONLY/PIT=false。

## 結果図：jQuantStats と価格・執行マーカー

最初に report model、sampling frequency、date span、price basis、fees、TOPIX source、`pit_guarantee=false` を確認します。jQuantStats は隣接 NAV の N−1 return intervals を分析し、初期資金から最初の NAV までは含みません。native NAV と全期間収益は元 report の初期資金口径です。別の分母と混同しません。日次年率252は report が `daily` を宣言した場合のみで、自然日や不規則な観測を JPX trading calendar と見なしません。

ダッシュボードは15組の概要図を順に表示します：jQuantStats の隣接 NAV return snapshot、元 report NAV、水中 drawdown、月次 return heatmap、観測窓の年次 return、rolling return/volatility/Sharpe、strategy/TOPIX 累積 return、期間 return 分布、cash/holding weights、FIFO fee-net closed-trade return、累積 realized P&L、累積実手数料、両側 gross turnover、保有数/最大 weight/HHI、検証できた security price contribution。その後に銘柄ごとの価格診断図と Regime panel が続きます。この参考 report では Off/unavailable、trace 0 件です。他の report が適格な履歴入力を明示した場合のみ timeline を表示できます。年次図は観測窓で、完全な暦年とは限りません。jQuantStats は隣接 NAV の N−1 区間を使い、初期資金から最初の NAV までを含みません。日次252期の年率換算は report が `daily` と明示した場合のみです。hover で日付、値、単位、軸、欠損を確認します。注文、fills、完了 position cycle の数は別です。

別の price/execution 図では raw price/indicator、prior-close order signal、actual open fill、skip を別々に読みます。signal date は execution date より前で、約定価格は始値です。TOPIX は配当なし価格指数で total return ではありません。実費用を再び差し引かず、買いと売り両側の gross turnover を one-way turnover と呼びません。注文数、約定数、完了したポジション周期は別概念です。

![jQuantStats スナップショット](../demos/research-20261006/ja_JP/dashboard-chart-01.png) ![月次 heatmap](../demos/research-20261006/ja_JP/dashboard-chart-04.png) ![TOPIX 対照](../demos/research-20261006/ja_JP/dashboard-chart-07.png) ![価格・シグナル・約定](../demos/research-20261006/ja_JP/dashboard-chart-16.png) ![Regime Off、unavailable、trace 0 件](../demos/research-20261006/ja_JP/dashboard-chart-19.png)

19図すべての画像リンク： [01 jQuantStats](../demos/research-20261006/ja_JP/dashboard-chart-01.png) · [02 NAV](../demos/research-20261006/ja_JP/dashboard-chart-02.png) · [03 drawdown](../demos/research-20261006/ja_JP/dashboard-chart-03.png) · [04 月次](../demos/research-20261006/ja_JP/dashboard-chart-04.png) · [05 年次観測窓](../demos/research-20261006/ja_JP/dashboard-chart-05.png) · [06 rolling risk](../demos/research-20261006/ja_JP/dashboard-chart-06.png) · [07 TOPIX](../demos/research-20261006/ja_JP/dashboard-chart-07.png) · [08 return 分布](../demos/research-20261006/ja_JP/dashboard-chart-08.png) · [09 cash/holdings](../demos/research-20261006/ja_JP/dashboard-chart-09.png) · [10 closed-trade return](../demos/research-20261006/ja_JP/dashboard-chart-10.png) · [11 realized P&L](../demos/research-20261006/ja_JP/dashboard-chart-11.png) · [12 fee](../demos/research-20261006/ja_JP/dashboard-chart-12.png) · [13 turnover](../demos/research-20261006/ja_JP/dashboard-chart-13.png) · [14 concentration](../demos/research-20261006/ja_JP/dashboard-chart-14.png) · [15 price contribution](../demos/research-20261006/ja_JP/dashboard-chart-15.png) · [16 4502 price/execution](../demos/research-20261006/ja_JP/dashboard-chart-16.png) · [17 6758 price/execution](../demos/research-20261006/ja_JP/dashboard-chart-17.png) · [18 8306 price/execution](../demos/research-20261006/ja_JP/dashboard-chart-18.png) · [19 Regime Off/unavailable、trace 0 件](../demos/research-20261006/ja_JP/dashboard-chart-19.png)

Concentration、contribution、内容のある Regime timeline は根拠入力が report にある場合だけ利用できます。この画像の Regime panel は Off/unavailable、trace 0 件です。図表は説明用で、戦略の有効性を証明しません。

### 費用・執行遅延の感度分析：report を固定して3シナリオを実行

「Backtest Results」で完了済みの `report.json` を開き、戦略と入力 identity を確認します。感度分析パネルの report path と SHA256 が選択した report と一致することを確認し、「固定3シナリオを実行」を押します。固定 source SHA は Native MA `Native MA report (SHA bound locally)`、TA-Lib MA `TA-Lib MA report (SHA bound locally)`、価格 momentum `price-momentum report (SHA bound locally)` です。後者は root が用意したオフライン研究 report で、GUI 作成の実行 receipt ではありません。source の bytes は変更されず、言語切替は再実行しません。

結果は3行・3 NAV 曲線です。0.1% は固定 recipe の再実行、0.2% は同じ戦略と行情で費用を上げて前終値数量を再計算する再実行、`+1 observed session` は baseline の数量を固定して次の実観測日始値で執行する診断です。遅延は新しいシグナル/銘柄選択でも、より良い戦略の選択でもありません。3ケースとも 2017-01-04～2022-12-30、1,464観測日です。

| 固定 source | シナリオ | 注文 | fill/skip | 費用 JPY | 期末 NAV | 期末 cash/equity JPY | 最大 DD |
|---|---|---:|---:|---:|---:|---:|---:|
| Native MA | 0.1% baseline | 64 | 45/19 | 64,251.25 | 1.10859189 | 13.94/2,217,183.77 | -30.70% |
| Native MA | 0.2% 再実行 | 64 | 45/19 | 126,492.57 | 1.07504194 | 13.53/2,150,083.89 | -31.38% |
| Native MA | +1日・数量固定 | 64 | 30/34 | 34,828.99 | 2.16391987 | 146,472.52/4,327,839.74 | -31.63% |
| TA-Lib MA | 0.1% baseline | 64 | 45/19 | 64,251.25 | 1.10859189 | 13.94/2,217,183.77 | -30.70% |
| TA-Lib MA | 0.2% 再実行 | 64 | 45/19 | 126,492.57 | 1.07504194 | 13.53/2,150,083.89 | -31.38% |
| TA-Lib MA | +1日・数量固定 | 64 | 30/34 | 34,828.99 | 2.16391987 | 146,472.52/4,327,839.74 | -31.63% |
| 価格 momentum | 0.1% baseline | 183 | 161/22 | 92,328.74 | 1.38670855 | 1,276,821.14/2,773,417.11 | -33.10% |
| 価格 momentum | 0.2% 再実行 | 184 | 168/16 | 182,846.64 | 1.25358260 | 9,737.31/2,507,165.19 | -41.32% |
| 価格 momentum | +1日・数量固定 | 183 | 128/55 | 59,240.38 | 1.32007157 | 192,816.23/2,640,143.15 | -38.01% |

Native MA と TA-Lib MA の3ケースは、この固定入力で同一の金融パスでした。遅延ケースの NAV が高く見えても選好根拠にしません。3行/3曲線、費用、fill/skip、期末値、最大DDを確認してください。private task は request/source hash と worker launch/result/exit log を記録し、公開 evidence summary は日次 JSON なしで比較概要を示します。金額は小数点以下2桁表示です。丸め表示ではなく bound report/account path を照合します。

![Native MA 感度分析 workbench](../demos/research-20261006/ja_JP/sensitivity-native-workbench.png) ![Native MA の3結果](../demos/research-20261006/ja_JP/sensitivity-native-results.png)
![TA-Lib MA 感度分析 workbench](../demos/research-20261006/ja_JP/sensitivity-talib-workbench.png) ![TA-Lib MA の3結果](../demos/research-20261006/ja_JP/sensitivity-talib-results.png)
![momentum 感度分析 workbench](../demos/research-20261006/ja_JP/sensitivity-momentum-workbench.png) ![momentum の3結果](../demos/research-20261006/ja_JP/sensitivity-momentum-results.png)

## Demo 4：歴史 Paper の step、全再生、読み取り専用再開

左ナビ「Paper Trading」→最初の「Historical market research replay」タブを選びます。「Legacy advanced features」タブは使いません。同じ frozen manifest と完成した price/composite strategy report、新規の未作成 account directory を指定します。初期現金、計画、source identity を確認し「Create isolated account」を押します。既存の本番 ledger を選びません。

「Open and verify」は読み取り専用です。「Step one day」で一つ進め、fill がない日には skip/cash/NAV を確認します。実際の約定日では signal/execution date、次の始値、side、qty、fee を照合します。「Run full history」で残りを再生し、completion receipt に全1,464観測日と最終日 2022-12-30 があることを確認します。申請した自然日数を観測数とみなしません。完了状態、account summary、fills/skips/fees を原策略 report と照合します。

![隔離 account 作成](../demos/research-20261006/ja_JP/paper-created.png) ![1観測日 step](../demos/research-20261006/ja_JP/paper-one-observed-day.png) ![実際の約定日](../demos/research-20261006/ja_JP/paper-actual-trade-day.png) ![全期間 replay](../demos/research-20261006/ja_JP/paper-full-history.png) ![最後の観測日](../demos/research-20261006/ja_JP/paper-last-observed-day.png) ![再オープン後の読み取り専用](../demos/research-20261006/ja_JP/paper-reopened-readonly.png)

アプリを閉じて同じ教材 account を再選択し、open/verify と「Read-only refresh」を行います。照会しても cursor は進まず、同じ cursor/idempotency key の再試行も重複イベントを作りません。manifest、report bytes、selected bars、replay code identity が変わったら fail closed にします。実行時の request/result/exit とログは GUI の task/history 画面で確認します。公開 summary は ledger や日次 account data を含みません。replay clock はデータの `available_at` ではありません。連続株数の研究 ledger は前向き Paper、JPX 当時可視性、単元株約定、broker 実行を意味しません。

## Demo 5：テスト endpoint、注文 mapping、read-only 境界

「Broker Connections」→最初の「Offline cash-equity mapping preview」タブを開きます。能力表は二つ目の advanced tab です。新規 workspace で test `http://127.0.0.1:18081` を選択します。account label/type、exchange と credential-reference 文字列は明示しますが、secret 自体は入力しません。「Save offline configuration」はローカル設定保存であり、reference 解決や token 発行をしません。

教材用 OrderIntent は code 6758、buy、qty 100、lot size 100、tick size 1、Asia/Tokyo の DAY 時刻を使います。必要な参考価格・fee・account/time は固定された教材用入力から指定し、キャッシュ価格をリアルタイム見積として扱いません。「Generate local mapping preview」を押すと mapped locally / not connected / not submitted とローカル receipt が表示され、`network_calls=0` であることを確認します。submit/cancel/token 操作はありません。

今回の mapping receipt は test port 18081、account type=4（指定口座）、exchange=9（SOR）を使います。参考価格、fee、口座ラベルと教材時刻は固定された教材設定に従います。

![test endpoint の設定](../demos/research-20261006/ja_JP/broker-test-config.png) ![有効な単元での offline mapping](../demos/research-20261006/ja_JP/broker-valid-local-mapping.png)

数量を101にして再実行すると lot size で BLOCKED、`network_calls=0` が期待値です。失敗 receipt は脱敏 error code のみで、注文 payload を保存しません。整手数量に戻せば再プレビューできます。test config、有効 mapping、101株 block の三語実 capture はすべてアーカイブ済みです。

read-only connection check は別操作です。専用の未定義環境参照 `env:DEMO_MISSING_TOKEN` を test config に指定して保存し、「Read-only check」を明示的に押します。worker は credential resolve 段階で `credential_missing`、GET 数0になるはずです。保存されるのは参照名だけです。この失敗診断は接続成功ではありません。有効な参照を指定した read-only check は localhost GET worker を開始し、端末に接続する可能性があるため、本コースでは未使用です。missing-reference の三語実 capture はアーカイブ済みです。workflow implemented の表示は terminal 接続を証明せず、production port 18080 も使いません。

<!-- section:evidence -->
## 画像・receipt・ログの場所

219枚は公開候補 source build を Qt で実行し、各 locale で実際に撮影した画像です。private workbench の画像でも、インストール wheel の証明でもありません。dashboard は概要15図、銘柄別価格/執行3図、Regime 1図の全19図です。sensitivity は別パネルです。media manifest に画像 path と hash を記録します。

| コース | 予定パス（`{locale}` は `zh_CN` / `ja_JP` / `en_US`） |
|---|---|
| Cache | `../demos/research-20261006/{locale}/cache-{selection,frozen}.png` |
| MA | `../demos/research-20261006/{locale}/ma-{native,talib}-{configured,results}.png` |
| Dashboard | `../demos/research-20261006/{locale}/dashboard-chart-01.png` ～ `dashboard-chart-19.png`；16～18 は4502/6758/8306、19 は Regime Off/unavailable・trace 0 件を表示 |
| Indicators | `../demos/research-20261006/{locale}/indicator-{talib,pandas_ta}-{controls,price-sma,rsi,macd,atr}.png` |
| Factor | `../demos/research-20261006/{locale}/factor-{input-and-recipe,ic-rank-ic,quantiles,coverage,turnover,correlation,observed-years}.png` |
| Studio | `../demos/research-20261006/{locale}/studio-factor-composite-{controls,results}.png`、`studio-both-models-{controls,results,remaining-results}.png`、`studio-lightgbm-score-results.png`、`studio-catboost-score-{controls,results}.png`、`studio-engines-20-60-{controls,results,remaining-results}.png` |
| Historical Paper | `../demos/research-20261006/{locale}/paper-{created,one-observed-day,actual-trade-day,full-history,last-observed-day,reopened-readonly}.png` |
| Broker | `../demos/research-20261006/{locale}/broker-{test-config,valid-local-mapping,blocked-101,readonly-missing-reference}.png`（すべてアーカイブ済み） |
| 感度分析 | `../demos/research-20261006/{locale}/sensitivity-{native,talib,momentum}-{workbench,results}.png` |
| 手册検索 | `../demos/research-20261006/{locale}/manual-course-demo-1.png`、`manual-search-broker.png` |

公開 evidence summary は `docs/demos/research-20261006/EVIDENCE_SUMMARY.md` です。公開画像の出所 identity、範囲、制限のみを記載します。実行ログは GUI の task/history 画面で確認してください。公開 package に local request、元帳、詳細 JSON、ユーザーの絶対 path は含めません。

感応度の画像と検証範囲は公開 evidence summary `docs/demos/research-20261006/EVIDENCE_SUMMARY.md` を参照します。3 source × 固定3ケースは独立財務パス監査済みですが、私有の日次明細や完全な receipt は公開しません。


