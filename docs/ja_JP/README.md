---
doc_id: readme
version: 1
locale: ja_JP
---

# KabuForge ドキュメント

<!-- section:contract -->
## 契約

KabuForge は、日本株のファクター、戦略、再現可能なバックテストに取り組む研究者・開発者向けのオープンソース・ローカル研究フレームワークです。

package `v0.1.1` が現在の安定版です（[GitHub Release](https://github.com/Siyuan-chat/KabuForge/releases/tag/v0.1.1)）。`main` は開発ブランチで、未リリースの変更を含む場合があります。Python、CLI、デスクトップ GUI、MCP は共通アプリケーションサービスを利用します。

オフラインの合成デモにデータキーは不要です。実市場データの利用条件や認証情報は選択する provider によって異なります。paper とバックテストの約定はシミュレーションであり、ブローカー約定ではありません。完全な過去 PIT 認証も提供しません。


<a id="quick-start"></a>
### クイックスタート / CLI

Python 3.12+

ソースのチェックアウト内で実行します：

```shell
git clone --branch v0.1.1 --depth 1 https://github.com/Siyuan-chat/KabuForge.git
cd KabuForge
python -m pip install .
kabuforge doctor
kabuforge demo --out output/demo
kabuforge factors
kabuforge strategies
```

### 始め方

- [クイックスタート / CLI](#quick-start)
- [開発の契約](DEVELOPMENT.md)

### 概念

- [アーキテクチャ](ARCHITECTURE.md)
- [研究の正確性とデータ制約](RESEARCH_METHODOLOGY.md)

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

### 貢献

- [貢献とライセンス](CONTRIBUTING.md)
- [セキュリティ](SECURITY.md)
- [変更履歴](CHANGELOG.md)
- [ロードマップ](ROADMAP.md)

<!-- section:evidence -->
## 証拠

`kabuforge doctor`, `kabuforge factors`, `kabuforge strategies`, `kabuforge demo` / Python 3.12+.

[English](../en_US/README.md) · [简体中文](../zh_CN/README.md) · [日本語](../ja_JP/README.md)
