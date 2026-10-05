---
doc_id: development
version: 1
locale: ja_JP
---

# 開発

<!-- section:contract -->
## 契約

GUI 内部や設定駆動 import ではなく package boundary に対して開発します。既存の `ApplicationService.register_factor(id, version, function, validator)` と `StrategyRegistry.register(StrategySpec, factory)` API は引き続き利用できます。validator は必須で、重複 identity は拒否されます。新しい `ResearchApplicationService` は、対応する固定研究操作向けの workspace 制限付き facade です。明示された file reference と recipe を受け取り、選択された optional 処理を静的 worker に委譲して、request/source hash、receipt、失敗 log を残します。GUI、CLI、MCP へのアクセスは、それぞれ対応済み adapter と allowlist に従います。すべての旧画面や command がこの facade を経由するとは限りません。ユーザー Python、任意 module path、任意 interpreter command は受け付けません。

決定的なローカル fixture を使ってください。local-cache 研究は歴史的な `available_at` を推測しません。その結果はすべて RESEARCH-ONLY、`pit_guarantee=false` です。raw 研究データ、credential、broker transport、private 実装を公開配布物へ含めないでください。模擬 fill、plan 意図、CLI の成功終了は実執行の証明ではありません。

公開ソースでは、明示的なローカルデータ選択、既定の価格 momentum、指標、factor/model/engine 研究、report、分離 Historical Paper、broker mapping/read-only 境界の GUI／worker workflow を検証しています。Python API と 14 個の固定 CLI／MCP 研究 route もソースで検証済みです。[統合マトリクス](INTEGRATIONS.md)と[5つの GUI 研究コース](GUI_RESEARCH_COURSES.md)を参照してから変更してください。

<!-- section:evidence -->
## 根拠

公開 package は `kabuforge`、Python 3.12+ とプロジェクト所有の資料には AGPL-3.0-only を適用し、第三者の通知を保持します。候補版 `0.2.0rc1` は未公開です。entry point は `kabuforge = kabuforge.cli:main` です。`public_source_manifest.json` で公開ソースを固定しますが、ソース検査だけでは wheel インストールや GUI 実行を証明しません。

GUI extra は Python 3.12 環境にインストールします。optional group (`analytics`、`indicators`、`models`、`backends`) は `pyproject.toml` にあります。必要な group だけ選んでください。optional operation が実行されたかは、package metadata や capability discovery だけでなく worker receipt で確認します。

```powershell
python -m pip install -e ".[gui]"
python -m framework_v2.cli --help
python -B -m unittest discover -s framework_v2/tests -q
python -B -m unittest discover -s tools/tests -p "test_sync_version.py" -q
```

source checkout から desktop workbench を起動します：

```powershell
python -B -m framework_v2.workbench_qt
```

このコマンドは対話 GUI を開くもので、headless または unattended test ではありません。配布版の受け入れを主張する場合は、対象 wheel のファイル名、SHA-256、version、Python／platform、インストール後の module origin を特定し、そのインストール済み artifact に対して必要な GUI／worker 検査を実行してください。source checkout の screenshot や source test は、インストール済み wheel の証明にはなりません。`0.2.0rc1` は未公開です。
