---
doc_id: adr_agent_boundary
version: 1
locale: ja_JP
---

# Agent のアプリケーション境界

<!-- section:contract -->
## 決定

Agent は検証済みコマンドとワークスペース内リソースを通じて共通サービスを操作します。任意の Python import、パス逸脱、ブローカー認証情報は受け付けません。既定の MCP は R0/R1 を登録します。R2 にはペーパーモードの明示的な有効化と永続的な冪等記録が必要です。信頼された承認機関とブローカー接続が実装されるまで R3 は無効です。

<!-- section:evidence -->
## 結果

統合設計のために無効な R3 schema を表示できますが、表示によって注文は許可されません。注文 API の参考：[Alpaca 公式 MCP](https://github.com/alpacahq/alpaca-mcp-server)。研究の実用性と実ブローカーの認証は独立した検証です。
