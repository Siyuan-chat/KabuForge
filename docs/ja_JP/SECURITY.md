---
doc_id: security
version: 1
locale: ja_JP
---

# セキュリティ

<!-- section:contract -->
## 契約

Agent input は schema 検証と credential-like value 検査を受けます。relative path は workspace 内で解決され、absolute path、traversal、root 外へ出る symlink、保護された credential/control location は拒否されます。workspace JSON read は 64 MiB、MCP line は 1 MiB に制限されます。

R2 mutation には caller 提供の call ID と idempotency key が要ります。R3 は無効です。human approval は将来の trusted host が一回だけ発行・消費し、Agent tool や config が作成してはいけません。

<!-- section:evidence -->
## 根拠

workspace SQLite の receipt は call ID、idempotency key、input/result hash、run ID、timestamp、tool、state を保存します。同じ idempotency key は永続済み outcome 又は不確実性拒否を返し、mutation を黙って繰返しません。
