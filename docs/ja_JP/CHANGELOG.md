---
doc_id: changelog
version: 1
locale: ja_JP
---

# 変更履歴

<!-- section:contract -->
## 契約

## 0.1.0-rc.1

local package CLI、制限 MCP adapter、型付け因子・戦略 registry、local Agent audit receipt、既定 R0/R1 catalog、明示的 R2 paper opt-in、予約済みで無効な R3 approval/order interface を導入し、公開 RC は公開 package と非公開のローカル workspace を分離し、公開ファクターの source identity を固定します。

<!-- section:evidence -->
## 根拠

既知の制限：Agent に real broker submission はありません。`--expose-reserved-external` は無効 stub のみを露出します。job は in-process daemon thread であり、再起動時に QUEUED/RUNNING job は `KF_JOB_INTERRUPTED` を伴う `FAILED` になり、自動 recovery/replay はありません。lookahead check は timestamp gate のみです。
