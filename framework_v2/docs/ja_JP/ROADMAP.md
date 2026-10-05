---
doc_id: roadmap
version: 1
locale: ja_JP
---

# ロードマップ

<!-- section:contract -->
## 契約

公開候補 `0.2.0rc1` は未公開です。研究フロー、移行したソース、5コース、19図レポート、cache/MCP を含む GUI／worker 経路をソース checkout で実際に確認しました。配布版の受け入れを主張する場合は、対象 wheel のファイル名、SHA-256、version、Python／platform、インストール後の module origin と操作別の検査結果を同じ artifact identity に結び付けてください。source receipt や screenshot はインストール済み wheel の証拠の代わりになりません。

### 現在のエンジニアリング段階

- 明示的に利用者が選んだローカルファイルから5つの研究フローを再現可能に保ちます：市場データの取込と identity、指標、因子評価、モデル/戦略/engine 比較、Historical Paper replay。ブローカーの mapping と明示的な read-only 診断は注文送信と分離します。
- 配布版の受け入れ記録は、特定した wheel を対応 Python 3.12 の隔離環境にインストールし、選択した操作の runtime を検査して artifact identity とともに保存します。ソース側の4つの optional runtime group、計31件の workflow test は skip なしで通過しました。これはローカル検証で、GitHub Actions 実行を意味しません。metadata や capability registry の表示だけでは計算成功の証明になりません。
- source hash、recipe、入力選択 identity、worker log、失敗 receipt を保持します。所有者の raw market cache、完全な report、model artifact、Paper ledger は package に含めません。
- すべての過去検証を RESEARCH-ONLY、`pit_guarantee=false` に保ちます。再生期間は既に観測済みの履歴であり、新しい out-of-sample 証拠や forward Paper ではありません。

### 今後の研究・エコシステム段階（v0.3以降）

- 信頼できる過去の利用可能時刻、改訂履歴、survivorship、取引所カレンダー、corporate action、配当の扱いを備えた strict PIT データ対応を進めます。download 日付をこれらの証拠として扱いません。
- readiness を引き上げる前に、現実的な capacity、liquidity、手数料、slippage、market impact、新しい forward-paper 観測を評価します。
- engine と broker の統合は、明示的な capability gate、再現可能な証拠、個別レビューを伴う場合に限り拡張します。実際の terminal 接続は未検証で、live submit/cancel は無効です。
- private Regime state-machine bridge は、別途移植・審査されない限り公開 build に含めません。公開版の Regime は既定で Off です。

これらは範囲を限定した後続作業です。将来の v1 にすべての研究・執行機能が含まれることを意味しません。

R3 取引 extension は trusted broker integration、human approval authority、action-bound one-time approval、durable submission/reconciliation journal、別途の明示的許可を前提とします。R3 schema や本 roadmap は許可を意味しません。

<!-- section:evidence -->
## 根拠

公開版の状態は[統合機能マトリクス](INTEGRATIONS.md)に記載しています。同マトリクスはソース実装、発見可能性、ソース実行、ソース GUI/worker 受け入れ、clean wheel/install、実端末検証を区別します。受け入れ済み参考実行は日本株3銘柄・1,464観測日ですが、データは利用者が用意し package には含まれません。制限と再現手順は[GUI研究コース](GUI_RESEARCH_COURSES.md)を参照してください。

従来の R3 境界は変わりません。R3 は既定 MCP catalog に無く、reserved stub を露出しても無効です。agent の非同期処理は in-process daemon thread で、interruption は fail-closed で扱います。
