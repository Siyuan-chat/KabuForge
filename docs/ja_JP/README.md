---
doc_id: readme
version: 1
locale: ja_JP
---

# KabuForge ドキュメント

<!-- section:contract -->
## 契約

KabuForge は研究者・開発者向けのオープンソースでローカル優先の日本株リサーチスタックです。ユーザー所有の J-Quants または明示的に選択したローカル価格データを、ファクター・モデル研究、バックテスト、ポートフォリオ／リスク確認、ブローカー計画へつなぎます。既定の研究戦略は価格モメンタムです。

package `v0.1.1` が現在の安定版です（[GitHub Release](https://github.com/Siyuan-chat/KabuForge/releases/tag/v0.1.1)）。`main` は開発ブランチで、未リリースの変更を含む場合があります。このソースチェックアウトは未公開の `0.2.0rc1` 候補です。バージョンは `pyproject.toml` または `kabuforge doctor` で確認してください。[公式ホームページ](https://kabuforge.com/) のバージョン欄は同じソースから生成されます。公開済みリリースは履歴であり、この候補版の識別には使いません。Python、CLI、デスクトップ GUI、MCP は共通アプリケーションサービスを利用します。

これは研究システムであり、ライブ取引を示すものではありません。過去期間の出力は RESEARCH-ONLY、`pit_guarantee=false` です。厳密な PIT、新しい将来期間での検証、PAPER-READY、実端末の接続は確認されていません。TOPIX は配当を含まない価格指数で、日付が完全一致する場合だけ結合します。公開ビルドの Regime は既定で Off であり、非公開 Regime ブリッジは含まれません。

<a id="quick-start"></a>
### クイックスタート / CLI

Python 3.12 以降が必要です。コアパッケージと任意依存グループは `pyproject.toml` に定義されています。利用する処理に必要なグループだけをインストールしてください。公開ソースの GUI／worker ワークフローと 14 件の CLI/MCP 研究ルートはソース上で検証済みです。クリーン wheel と分離環境でのインストール済みワークフロー受け入れ証拠は別に管理しています。ソースのスクリーンショットだけではインストール済み配布物を証明しません。現在の `0.2.0rc1` 候補は未公開です。

現在の安定パッケージを使う場合は、固定した release source を取得します。

```shell
git clone --branch v0.1.1 --depth 1 https://github.com/Siyuan-chat/KabuForge.git
cd KabuForge
python -m pip install .
```

開発ソースは `main` ブランチから取得してください。未公開の変更が含まれる場合があります。

```shell
python -m pip install .
python -m pip install ".[gui,analytics,indicators,models,backends]"
kabuforge doctor
python -m framework_v2.workbench_qt
```

GUI の手順は[三言語・五コースガイド](GUI_RESEARCH_COURSES.md)を参照してください。同梱のオフラインマニュアルには検索可能な 24 章があります。入力はユーザーが明示的に選択する CSV、Parquet、または完了済み manifest です。市場データキャッシュ、完全なレポート、モデル成果物、認証情報、Paper 台帳は同梱しません。ソース実装、runtime の検出、ソース上の実行証拠、配布物の受け入れ、ブローカー確認の違いは[統合機能マトリクス](INTEGRATIONS.md)に記載しています。

### 始め方

- [クイックスタート / CLI](#quick-start)
- [GUI コースと検索可能なマニュアル](GUI_RESEARCH_COURSES.md)
- [開発の契約](DEVELOPMENT.md)
- [ロードマップ](ROADMAP.md)

### 概念

- [アーキテクチャ](ARCHITECTURE.md)
- [研究の正確性とデータ制約](RESEARCH_METHODOLOGY.md)
- [統合機能マトリクス](INTEGRATIONS.md)

### API

- [ファクター：登録と検証器](FACTOR_API.md)
- [戦略：意思決定と目標](STRATEGY_API.md)
- [MCP：アクセスと呼び出し証拠](AGENT_API.md)
- [執行：シミュレーションと UNKNOWN](EXECUTION.md)
- [ブローカー mappings と mock](BROKER_API.md)

### 検証

- [検証と従来のリリース制約](RELEASE_PROCESS.md)
- [Python 3.12 リリース基盤 CI](https://github.com/Siyuan-chat/KabuForge/actions/workflows/kabuforge.yml)
- [リリース手順](RELEASE_PROCESS.md)
- [未公開候補とバージョンソース](https://kabuforge.com/)

### 貢献

- [貢献とライセンス](CONTRIBUTING.md)
- [セキュリティ](SECURITY.md)
- [変更履歴](CHANGELOG.md)
- [ロードマップ](ROADMAP.md)

<!-- section:evidence -->
## 根拠

ソースレベルの参照実行には、ローカルキャッシュ、指標、ファクター／モデル／エンジン、過去 Paper、ブローカーのプレビュー、感度分析が含まれます。詳細は[コース](GUI_RESEARCH_COURSES.md)と[機能マトリクス](INTEGRATIONS.md)を参照してください。公開 GUI／worker 経路と 14 件の CLI/MCP 研究ルートもソース上で検証済みです。クリーン wheel と分離環境でのインストール済みワークフロー受け入れ証拠は別に管理しており、ソース実行やスクリーンショットだけでは配布物を認証しません。ブローカー mapping はオフラインです。明示的に要求する読み取り専用診断は別機能であり、どちらも実端末接続を証明しません。注文送信と取消は無効です。

`kabuforge doctor` はインストール済み／ソース配布物のバージョンとローカル機能を表示します。[ホームページ](https://kabuforge.com/)のバージョン欄はプロジェクトのバージョンソースから生成されます。[リリース一覧](https://github.com/Siyuan-chat/KabuForge/releases)は過去に公開された成果物を確認するためのものです。

[English](../en_US/README.md) · [简体中文](../zh_CN/README.md) · [日本語](../ja_JP/README.md)
