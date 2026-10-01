---
doc_id: roadmap
version: 1
locale: ja_JP
---

# ロードマップ

<!-- section:contract -->
## 契約

本 RC は既存公開実装を独立して install 可能にします。次は fixture、data provenance、dependency review を拡充し、timestamp gate を超える研究検証と run 再現性の証拠を強化します。

R3 取引 extension は trusted broker integration、human approval authority、action-bound one-time approval、durable submission/reconciliation journal、別途の明示的許可を前提とします。R3 schema や本 roadmap は許可を意味しません。

<!-- section:evidence -->
## 根拠

現在 R3 は既定 MCP catalog に無く、reserved stub を露出しても無効です。非同期 job は in-process daemon thread で、interruption は fail-closed で扱います。
