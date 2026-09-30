# KabuForge · JP Equity Backtest Console

[简体中文](README.md) · [日本語](README.ja.md) · [English](README.en.md)

![KabuForge](brand/kabuforge/v1/logo-horizontal-light.png)

**日本株の調査、再現可能なシミュレーション、検証可能な執行記録のためのローカル・デスクトップ・ワークベンチです。**

KabuForge は、このリポジトリの次世代リサーチ・ワークベンチです。中国語／日本語／英語の三言語 UI、ガイド付き戦略フォーム、オフライン・マニュアル、公開因子、厳格なデータ識別子チェック、シグナルと約定を分離したシミュレーション・エンジンを備えています。リポジトリ名は `JP-Equity-Backtest-Console` から `KabuForge` に変更され、旧リンクは GitHub が自動的に転送します。旧 GUI / CLI も引き続き利用でき、[旧版の説明](docs/LEGACY_README.md)を参照できます。

このリリースで用いるのは、本リポジトリの `factors/` に既にある**公開因子**だけです。標準の 12-1 モメンタムは `public.momentum_12_1` として識別されます。著者の非公開の残差モメンタムやその他の非公開因子は、含まれず、インポートされず、代替もされません。市場データ、口座記録、認証情報はコードとともに配布されません。

## クイックスタート

Windows、Python 3.12、PowerShell 7 が必要です。リポジトリのルートで実行してください。

```powershell
py -3.12 -m venv .venv-gui
.\.venv-gui\Scripts\python.exe -m pip install -r framework_v2/requirements-gui.txt
.\Launch_KabuForge.bat
```

インストール後は、`Launch_KabuForge.bat` をダブルクリックして起動できます。ホーム画面でオフライン・デモを選び、戦略を作成し、シミュレーションを実行して結果を確認します。ランチャー自体は依存関係をインストールしません。旧エントリーポイント `start_here.bat` は引き続き旧 GUI を起動します。

直接実行することもできます。

```powershell
.\.venv-gui\Scripts\python.exe -B -m framework_v2.workbench_qt --workspace output/my_workspace
```

## プレビュー

既存の中国語・日本語・英語の操作デモをそのまま利用します。GIF とスクリーンショットは変更していません。これらは過去の調査フローを示すものであり、今回公開する因子の結果を表すものではありません。デモには元の価格データ、戦略設定、帳簿は含まれません。

| 中国語 | 日本語 | 英語 |
| --- | --- | --- |
| [操作デモ](docs/demos/zh_CN/index.html) | [操作デモ](docs/demos/ja_JP/index.html) | [Workflow demo](docs/demos/en_US/index.html) |

![日本語操作デモ](docs/demos/ja_JP/workflow.gif)

[三言語デモの一覧](docs/demos/index.html) · [中国語 GIF](docs/demos/zh_CN/workflow.gif) · [English GIF](docs/demos/en_US/workflow.gif)

## ドキュメント

| 内容 | 入口 |
| --- | --- |
| インストール、起動、操作 | [操作ガイド](docs/OPERATIONS.md)（中国語） |
| ステップごとのオフライン・デモ | [デモ・チュートリアル](docs/DEMO.md)（中国語） |
| モジュール、データフロー、執行境界 | [詳細アーキテクチャ](docs/ARCHITECTURE.md)（中国語） |
| エンジンのインターフェースと制限 | [エンジン文書](framework_v2/README.md)（中国語） |
| オフライン完全マニュアル | [日本語](framework_v2/docs/manual_ja_JP.html) · [中国語](framework_v2/docs/manual_zh_CN.html) · [English](framework_v2/docs/manual_en_US.html) |
| 今回のリリース検証 | [検証記録](docs/RELEASE_VALIDATION.md)（英語） |
| 旧版の設定と操作 | [旧版 README](docs/LEGACY_README.md)（英語） |

HTML マニュアルはリポジトリをダウンロードしてブラウザーで開くか、ワークベンチで F1 を押して開いてください。GitHub のファイル画面ではソースコードが表示されます。

## オフライン CLI デモ

以下のコマンドはリポジトリのルートで実行し、毎回新しい出力ディレクトリを使用してください。

```powershell
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli demo --out output/demo
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli validate output/demo/backtest.json
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli history output/demo/backtest.json --timeline output/demo/timeline.json --out output/history
```

`demo` は backtest、paper、fake の 3 モードで注文意図が一致することを確認し、注文は送信しません。`history` はローカル・シミュレーションの純資産価額（NAV）、注文、約定、ログを生成します。デモは合成入力を用いるため、実際の収益を証明するものではありません。

## エンジンの主な特徴

- 設定の参照グラフ、データ・スナップショット、因子実装はすべて ID とコンテンツハッシュに結び付けられます。
- 因子が読めるのは、意思決定時点で `available_at` により既知と示されたデータだけです。現在の API ダウンロード結果から過去の PIT 証明が自動的に得られることはありません。
- シグナル、リスク制約、数量計画、シミュレートした約定を分離します。後から得た執行価格を過去の目標の選び直しには使いません。
- SQLite トランザクションに注文、イベント、約定、口座バージョン、意思決定の証跡を記録します。注文状態が不明な場合は、根拠のない再送を防ぎます。
- 三言語 UI、オフライン全文検索マニュアル、再度開ける戦略ドラフト、実行記録、読み取り専用帳簿を提供します。
- J-Quants v2 のデータダウンロードはページング、中止、再開、ローカル完全性チェックに対応します。利用資格は利用者自身で用意してください。

## 対象範囲と制限

本ソフトウェアは調査とシミュレーションのためのものであり、投資助言でも実取引システムでもありません。実際の証券会社接続、Excel のローカル統合、履歴タスクの自動復旧、戦略の有効性認定は未提供です。プロトコルアダプターと mock テストは、利用可能な実際の証券会社接続を意味しません。

日次バーをダウンロードした後の簡易価格調査と、厳格な PIT エンジンではデータ契約が異なります。前者は端数株を許容した株数を用い、完全な売買単位、スリッページ、配当、容量監査を含みません。旧来の完全なコンポジット／regime アルゴリズムとの等価な移植は主張しません。詳細は [DISCLAIMER](DISCLAIMER.md) と [LICENSE](LICENSE) を参照してください。

## 開発時のチェック

```powershell
.\.venv-gui\Scripts\python.exe -B -m unittest discover -s framework_v2/tests -q
.\.venv-gui\Scripts\python.exe -B -m framework_v2.capture_acceptance --output output/gui_acceptance
```

受入スクリプトは Qt のオフスクリーン・コントロールと合成/mock 入力を使用します。ネイティブなマウス自動化、実際の API 権限テスト、実取引の認定を行うものではありません。
