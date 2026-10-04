---
doc_id: release_process
version: 1
locale: ja_JP
---

# Release Process

<!-- section:contract -->
## 契約

公開正式版は `0.1.1`、package `kabuforge`、GitHub release tag `v0.1.1` です。公開 factor/runtime ソースは既存公開 baseline に固定します。非公開のローカル workspace は別配布物であり、公開 factor packaging の入力にしません。test、独立 wheel install、source/wheel/sdist 境界 audit、CI が成功した後に公開します。release は取引を許可しません。

<!-- section:evidence -->
## 証拠

`public_source_manifest.json` は正規化 source hash を固定します。`tools/check_public_distribution.py` は出典の変更、root の非公開 runtime、生成状態、認証情報を拒否します。公開 wheel、source archive、checksum を release asset とします。GitHub CI は Windows/Ubuntu、API/CLI/MCP、文書 parity を検証します。R3 は既定で登録せず、予約 hook を表示しても無効のままです。
