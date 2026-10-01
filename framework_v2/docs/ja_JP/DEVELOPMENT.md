---
doc_id: development
version: 1
locale: ja_JP
---

# 開発

<!-- section:contract -->
## 契約

GUI 内部や設定駆動 import ではなく package boundary に対して開発します。信頼済み因子は `ApplicationService.register_factor(id, version, function, validator)`、戦略は `StrategyRegistry.register(StrategySpec, factory)` で登録します。validator は必須で重複 ID は拒否されます。

決定的なローカル fixture を使ってください。研究データ、credential、broker transport、private 実装を公開配布物へ含めてはいけません。模擬 fill、plan 意図、CLI の成功終了は実執行の証明ではありません。

<!-- section:evidence -->
## 根拠

公開 package は `kabuforge`、Python 3.12+ と既存 MIT license を使用します。entry point は `kabuforge = kabuforge.cli:main` です。`public_source_manifest.json` で公開ソースを固定し、source/wheel/sdist を検査します。
