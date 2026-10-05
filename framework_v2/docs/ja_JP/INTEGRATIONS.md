---
doc_id: integrations
version: 1
locale: ja_JP
---

# 統合機能とワークフローのマトリクス

<!-- section:contract -->
## 契約

このマトリクスは公開候補のソース実装と実行証拠を区別します。9項目の移行済み研究実装について、5コースの GUI、19図レポート、cache/MCP を含むソース checkout の GUI/worker 経路を実際に検証済みです。これはクリーン wheel のインストールや利用者環境での optional runtime 受け入れを意味しません。「発見可能」は一覧表示を指し、計算成功とは別です。

例はすべて RESEARCH-ONLY で、`pit_guarantee=false` です。入力は利用者が明示する CSV、Parquet、または完了済み manifest です。生の J-Quants キャッシュ、完全なレポート、モデル成果物、認証情報、Paper 台帳は同梱しません。検証済み参考フローは[5つの GUI 研究コース](GUI_RESEARCH_COURSES.md)、画像の出所と範囲は[公開証拠サマリー](../demos/research-20261006/EVIDENCE_SUMMARY.md)を参照してください。

| 状態の軸 | データ | 指標 | モデル | バックテスト | ブローカー |
|---|---|---|---|---|---|
| ソース実装 | J-Quants connector と、明示的なローカルキャッシュ読込、検証、選択バーの freeze、identity 確認。 | 分離 worker での TA-Lib と native `pandas-ta`。Native MA は戦略経路であり、汎用指標 provider ではありません。 | 時系列分割と label 境界 purging を備えた固定 LightGBM/CatBoost 研究レシピ。 | 因子/モデルスコア戦略、Native/VectorBT/Backtrader 固定注文リプレイ、ダッシュボード、感度診断、分離された Historical Paper リプレイ。 | オフライン注文マッピングと、明示的に実行する read-only 現金/保有/注文診断。submit/cancel は無効。 |
| 発見可能性 | ローカル入力形式とフローを文書化。GUI 機能はインストールされたビルドに依存。 | provider/runtime metadata を一覧可能。利用可否はメインプロセスの import ではなく分離 worker が決定。 | モデルワークフローと固定モデルを一覧可能。optional runtime の解決は discovery と別。 | 戦略、エンジン、レポート、Historical Paper を個別に一覧可能。一覧表示は成功 receipt ではない。 | マッピングと read-only 機能は別。認証情報参照は端末接続を意味しない。 |
| ソース実行証拠 | 参考結果は既存のローカル J-Quants キャッシュを使用。生価格4,392行、2017-01-04〜2022-12-30の共通観測日1,464日。オンライン要求を検証したものではありません。 | 両 provider で1,464日の参考系列を生成し、指標計算を独立照合。 | 2モデルが各2,190件の過去予測を生成。checkpoint 再読込後も予測差は報告上ゼロ。 | 因子研究では4,209件の feature 行と4,392件の forward-label/evaluation 行を分離。因子戦略1,464日、モデル戦略489日。固定20/60比較で4エンジン候補が一致。Historical Paper は1,464日、約定156件、skip 11件。手数料/遅延9シナリオは独立した金融パス会計と一致。 | ソースはオフラインマッピングに対応。read-only 呼び出しのソース経路は実装済みだが、実ブローカー端末は未検証。 |
| ソース GUI/worker 受け入れ | ローカル cache の選択、検証、freeze を実際に操作。オンライン J-Quants 要求は含まない。 | TA-Lib と pandas-ta の隔離 worker を実データ範囲で実行し、GUI 図を確認。 | LightGBM/CatBoost の固定 split GUI 経路を実行。モデル別6チェックは skip なし。 | 5コース、19図 dashboard、factor/model/engine、Paper、9件の感度シナリオをソース GUI で実行・照合。cache/MCP 経路も確認済み。 | offline mapping と明示的 read-only パネルのソース GUI 経路を確認。missing reference は0 GET。実端末は未検証。 |
| clean wheel/package 受け入れ | ゲート: SHA-256 と version で特定した wheel を隔離 `-I` 環境へ install し、導入済みモジュールの所在を記録して local-cache workflow を実行します。ソース GUI の証拠だけではインストール済み package の証明になりません。 | ゲート: wheel の SHA-256/version と隔離 `-I` install を記録し、導入済みモジュールの所在を確認して選択した indicator provider を宣言済み optional runtime で実行します。ソース GUI の証拠だけではインストール済み package の証明になりません。 | ゲート: wheel の SHA-256/version、隔離 `-I` 環境、導入済みモジュールの所在を実行に結び付け、選択した learner の結果を保存します。ソース確認だけでは導入済み worker の証明になりません。 | ゲート: 選択した backtest operation を wheel の SHA-256/version と隔離 `-I` のモジュール所在に結び付け、実行結果を保存します。ソース GUI の証拠だけでは配布後の worker 起動を証明しません。 | ゲート: offline mapping と明示的に要求した read-only operation を wheel の SHA-256/version、隔離 `-I` のモジュール所在に結び付け、実行証拠を保存します。実端末の検証や注文機能の有効化を意味しません。 |
| 実端末検証 | 該当なし。 | 該当なし。 | 該当なし。 | 該当なし。 | 未検証。明示的な read-only 要求には設定済み参照が必要。オフラインマッピング preview はネットワーク要求を行いません。注文の submit/cancel は行いません。 |
| 証拠と制限 | 参考入力はローカル J-Quants キャッシュ、benchmark は実際の TOPIX 終値価格指数です。配当を含まず、NAV 日付に厳密一致させます。歴史的な利用可能性は証明しません。 | SMA/RSI/MACD/ATR は初期化と warm-up が明記された provider 出力です。指標が signal や order になるわけではありません。 | train 2017–2019、validation 2020、過去診断 2021–2022、seed 42。test 期間は既知の過去で、新しい OOS ではありません。 | 固定レシピに基づき数量、手数料、skip、価格を再計算します。口座パスの一致は全エンジンで約定列が一致する意味ではありません。Paper は連続株数の過去リプレイであり、forward Paper ではありません。 | マッピングは認証情報そのものではなく参照を扱います。歴史的 PIT、承認付き実取引、端末操作、実注文は提供しません。 |

## 状態の読み方

ソース checkout の GUI/worker 経路は実行検証済みですが、clean wheel/package の受け入れとは別です。4つの optional runtime group では合計31件のソース workflow test が skip なしで通過しました。これはローカル確認であり、GitHub Actions の実行結果ではありません。provider の発見や engine の一覧は runtime 成功の証拠ではありません。read-only 診断は明示的に実行し、0 network の offline preview と区別します。実端末は未検証です。研究結果は strict PIT、投資可能、PAPER-READY、実取引の証拠にはなりません。

## 次の作業

[ロードマップ](ROADMAP.md)に、残る clean wheel/install acceptance と長期研究要件を記載しています。主な研究課題は信頼できる過去の利用可能時刻、取引カレンダー、コーポレートアクション、配当、容量と現実的な執行コスト、新しい forward 観測です。公開 Regime は既定で Off で、非公開の state-machine bridge は含まれません。

<!-- section:evidence -->
## 証拠

ソース checkout で受け入れた GUI デモと制限は[GUIコースガイド](GUI_RESEARCH_COURSES.md)と公開証拠サマリーに記載されています。画像と出所の要約のみを含み、生データ、完全レポート、model checkpoint、Paper 台帳は含めません。source GUI の受け入れは clean wheel のインストール証明ではなく、実ブローカー端末への接続や実取引有効化も示しません。
