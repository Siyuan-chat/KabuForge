---
doc_id: architecture
version: 1
locale: ja_JP
---

# アーキテクチャ

<!-- section:contract -->
## 契約

KabuForge には異なる契約を持つ二つのサービス層があります。既存の `ApplicationService` はレガシーの意思決定境界です。検証済み設定を解決し、許可リストに登録された因子・戦略 registry を使い、研究価格と執行 quote を分離して plan を返します。注文送信、ledger 書込み、ブローカーへの接続は行いません。戦略設定が選べるのは登録済み実装 identity だけで、コードを動的 import しません。この層を使う既存 caller の `available_at` と執行 timeline の規則も維持します。

共有 `ResearchApplicationService` は固定されたローカル研究コアを呼ぶアダプターであり、金融計算エンジンの置き換えではありません。明示的なファイル参照と固定 recipe を受け取り、選択入力・ソース identity を検証し、workspace 内に task 成果物を作成します。request、起動、成功／失敗 receipt とログを保持します。CLI と MCP は合わせて 14 個の固定研究操作を提供し、それぞれに独自の allow-list があります。GUI にも別の操作境界があり、すべてのレガシー画面やコマンドが facade 経由とは限りません。各 adapter は固定コアを再実装しません。request からコード、module import、shell command、interpreter path は指定できません。モデル、指標、バックエンドの任意依存は選択した操作ごとに検査し、定義済みの静的 worker で実行します。GUI メインプロセスに重い任意ライブラリを import しません。

二つの入力契約を混同しません。レガシー snapshot は明示的な `available_at` と可視性検査を要求できます。過去日足研究は、選択した CSV／Parquet／snapshot／完了済み manifest を明示的に固定し、coverage、価格口径、ソース／選択 hash、仮定を記録します。過去の利用可能時刻を後付けで作りません。結果は `RESEARCH-ONLY`、`pit_guarantee=false` です。

Agent facade は独自の workspace 境界、JSON Schema 検証、認証情報走査、永続 call receipt、ローカル SQLite 監査状態を保持します。`.git`、`.aws`、`.codex`、secret、credential、監査 DB は参照できません。Historical Paper は明示 opt-in で新規作成する独立した追記専用の研究 replay です。レガシー執行 ledger やリアルタイム／将来期間の Paper 口座ではありません。

オフライン broker mapping は通信しない transport を使い、secret を解決しません。別途明示的に実行する読み取り専用チェックでは、設定済み参照を解決して設定されたローカル endpoint に cash、positions、orders の GET を行います。実際の broker terminal は検証されていません。注文送信と取消は無効です。R3 は既定 MCP catalog に存在せず、予約済み stub の表示も有効化や権限付与を意味しません。

<!-- section:evidence -->
## 根拠

既定のレガシー strategy registry は `composite_factor` version `1` を登録し、組込み factor identity はローカル `BuiltinFactors` に由来します。新しい research flow の既定戦略は価格モメンタムです。日足 cache freeze と factor cache は明示的な identity 結合を行い、factor cache を使うのは接続済みの factor-strategy 経路に限られます。レガシーの全データ／factor 経路を cache 化するものではありません。factor feature rows と forward-label 評価 rows は別成果物です。固定 LightGBM/CatBoost は時系列 train／validation／historical-test 分割と label 境界の purge を使います。Native、VectorBT、Backtrader は固定注文を独立 replay します。口座経路の一致は、すべての入力で約定 stream が同一という意味ではありません。

テクニカル指標 provider は TA-Lib と native `pandas-ta` の二つです。任意 runtime は全ライブラリを GUI main process に import せず、静的 worker gate で選択操作ごとに確認します。report dashboard は暗色 19 図（15 のサマリー、銘柄別の価格／執行図 3 枚、Regime 図 1 枚）と、別の固定手数料／遅延感度パネルを持ちます。TOPIX は配当なし価格指数で、NAV と日付が完全一致する値だけ結合します。参照レポートの Regime 図は Off／unavailable、trace 0 件です。公開ビルドは Regime Off を既定とし、非公開状態機械 bridge を除外します。組込みオフライン help には三言語の研究コースを含む検索可能な 24 章があります。

ソース候補 `0.2.0rc1` は未公開です。公開 GUI／worker workflow と Python、CLI、MCP の研究 route はソースに対して検証済みです。配布版の受け入れを主張する場合は、対象 wheel のファイル名、SHA-256、version、Python／platform、インストール後の module origin を特定し、そのインストール済み artifact に対する操作別の検査結果を記録してください。source screenshot と source test はインストール済み wheel の証拠ではありません。データ例はユーザー提供であり、同梱されません。過去レポートは RESEARCH-ONLY／PIT false であり、strict PIT、新鮮な OOS、PAPER-READY、実執行の証拠ではありません。
