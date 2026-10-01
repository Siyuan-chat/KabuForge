---
doc_id: readme
version: 1
locale: ja_JP
---

# KabuForge ドキュメント

<!-- section:contract -->
## 契約

以下の入口を選んでください。パッケージ版は 0.1.0rc1、公開済み v0.1.0 Release は RC 添付物を保持します。実取引や完全な過去 PIT 認証は提供しません。


ソースのチェックアウト内で実行します：

```shell
python -m pip install .
kabuforge doctor
kabuforge demo --out output/demo
kabuforge factors
kabuforge strategies
```

### 始め方

- [クイックスタート / CLI](DEVELOPMENT.md)
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
