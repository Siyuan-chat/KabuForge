# KabuForge · JP Equity Backtest Console

[简体中文](README.md) · [日本語](README.ja.md) · [English](README.en.md)

![KabuForge](brand/kabuforge/v1/logo-horizontal-light.png)

**日本株の投資戦略を手元の PC で検証するためのデスクトップアプリです。**

KabuForge では、フォームに沿って戦略を設定し、バックテストを実行して、注文・約定・資産推移を確認できます。画面は日本語・中国語・英語に対応しています。オフラインで読める操作マニュアルに加え、設定や入力データの変更を検出する仕組みを備え、同じ条件で検証をやり直せるようにしています。

リポジトリ名は `JP-Equity-Backtest-Console` から `KabuForge` に変更されました。旧 URL からもアクセスできます。従来の GUI と CLI については、[旧版 README（英語）](docs/LEGACY_README.md)をご覧ください。

本リポジトリで使用するのは、`factors/` に収録された**公開ファクターのみ**です。12-1 モメンタムの実装 ID は `public.momentum_12_1` です。作者が別途使用している非公開ファクターは含まれておらず、公開ファクターがそれらと同じ計算を行うわけではありません。市場データ、口座記録、API キーなどの認証情報も同梱していません。

## インストールと起動

Windows、Python 3.12、PowerShell 7 を用意し、リポジトリのルートディレクトリで次のコマンドを実行してください。

```powershell
py -3.12 -m venv .venv-gui
.\.venv-gui\Scripts\python.exe -m pip install -r framework_v2/requirements-gui.txt
.\Launch_KabuForge.bat
```

インストール後は `Launch_KabuForge.bat` をダブルクリックするだけで起動できます。まずはホーム画面からオフラインデモを開き、戦略の作成、シミュレーションの実行、結果の確認をお試しください。起動用のバッチファイルは、必要なパッケージを自動でインストールしません。従来の `start_here.bat` は引き続き旧版 GUI の起動に使えます。

作業データの保存先を指定して起動する場合は、次のコマンドを使います。

```powershell
.\.venv-gui\Scripts\python.exe -B -m framework_v2.workbench_qt --workspace output/my_workspace
```

## 操作デモ

日本語画面での操作を収録した既存のデモです。GIF とスクリーンショットは収録時のまま掲載しています。画面内の資産推移は過去の検証例であり、今回の公開ファクターで得られた結果を示すものではありません。元の市場データ、戦略設定、取引記録は付属していません。

![日本語画面の操作デモ](docs/demos/ja_JP/workflow.gif)

[スクリーンショットを見る](docs/demos/ja_JP/index.html) · [GIF を開く](docs/demos/ja_JP/workflow.gif)

## ドキュメント

| 内容 | リンク |
| --- | --- |
| 操作方法 | [日本語マニュアル](framework_v2/docs/manual_ja_JP.html) |
| インストールと実行手順 | [操作ガイド（中国語）](docs/OPERATIONS.md) |
| オフラインデモの実行手順 | [デモガイド（中国語）](docs/DEMO.md) |
| モジュール構成とデータの流れ | [アーキテクチャ（中国語）](docs/ARCHITECTURE.md) |
| エンジンの仕様と制約 | [エンジンの説明（中国語）](framework_v2/README.md) |
| 公開前に実施したテスト | [検証記録（英語）](docs/RELEASE_VALIDATION.md) |
| 旧版の設定と操作方法 | [旧版 README（英語）](docs/LEGACY_README.md) |

HTML 形式のマニュアルは、リポジトリをダウンロードしてブラウザーで開いてください。アプリ内では F1 キーで開けます。GitHub のファイルページでは HTML のソースが表示されます。

## コマンドラインでデモを実行する

以下のコマンドはリポジトリのルートディレクトリで実行します。再実行するときは、既存の結果と重ならないように出力先を変更してください。

```powershell
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli demo --out output/demo
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli validate output/demo/backtest.json
.\.venv-gui\Scripts\python.exe -B -m framework_v2.cli history output/demo/backtest.json --timeline output/demo/timeline.json --out output/history
```

`demo` は、`backtest`・`paper`・`fake` の各モードで同じ注文案が生成されることを確認します。実際の注文は送信しません。`history` はローカル環境でシミュレーションを行い、資産推移（NAV）、注文、約定、ログを出力します。このデモにはテスト用の架空データを使用しており、実際の運用成績を示すものではありません。

## 主な機能

- **検証条件の記録**：設定ファイル、その参照先、入力データ、ファクターの実装に識別子とハッシュを付け、内容の変更を検出します。
- **将来の情報の混入を防ぐ仕組み**：ファクターの計算に使えるのは、`available_at` が示す利用可能時刻が判断時点以前のデータだけです。ただし、現在の API から取得したデータが過去にも同じ内容で利用できたことまでは保証しません。
- **判断と約定の分離**：銘柄選定、リスク制約、注文数量の計算、約定シミュレーションを分けています。後から判明した約定価格で、過去の銘柄選定をやり直すことはありません。
- **取引処理の記録**：注文、イベント、約定、口座状態の更新履歴、判断の根拠を SQLite に保存します。注文の状態が不明な場合は、確認せずに再送することを防ぎます。
- **操作と結果確認**：三言語の画面、全文検索できるオフラインマニュアル、保存した戦略設定の再読み込み、実行履歴、取引記録の閲覧に対応しています。
- **J-Quants v2 からのデータ取得**：複数ページに分かれたデータの取得、ダウンロードの中止・再開、保存データの整合性チェックに対応しています。API の利用に必要な契約・認証情報は各自で用意してください。

## 利用上の注意と未対応の機能

本ソフトウェアは研究とシミュレーションを目的としています。投資助言や実際の注文発注を行うシステムではありません。実口座への接続、実環境での Excel 連携、中断したバックテストの自動再開は未対応です。戦略の有効性を保証するものでもありません。接続用コードや模擬テストが含まれていても、証券会社との接続が実環境で確認済みという意味ではありません。

ダウンロードした日足データを使う簡易分析と、各時点で利用可能だった情報だけを扱う PIT（Point-in-Time）エンジンでは、入力データの要件が異なります。簡易分析では株数を整数に限定せずに計算します。売買単位、スリッページ、配当、市場の流動性に応じた取引可能額を十分に考慮した検証は行っていません。また、旧版の複合スコア計算や相場局面判定の仕組みをすべて再現しているわけではありません。[免責事項](DISCLAIMER.md)と[ライセンス](LICENSE)もご確認ください。

## 開発者向けのテスト

```powershell
.\.venv-gui\Scripts\python.exe -B -m unittest discover -s framework_v2/tests -q
.\.venv-gui\Scripts\python.exe -B -m framework_v2.capture_acceptance --output output/gui_acceptance
```

画面の検証スクリプトでは、テスト用データと模擬 API 応答を使い、Qt の画面をオフスクリーンで描画します。OS 上でのマウス操作や実際の API 利用権限を確認するテストではなく、実取引への対応を保証するものでもありません。
