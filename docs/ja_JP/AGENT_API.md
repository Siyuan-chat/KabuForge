---
doc_id: agent_api
version: 1
locale: ja_JP
---

# Agent API

<!-- section:contract -->
## 契約

stdio MCP server は明示的に境界を設定した workspace で起動します。既存 agent tools に加え、共有 `ResearchApplicationService` を呼ぶ 14 個の固定ローカル研究操作を提供します。各 tool は閉じた JSON schema を持ち、workspace 内の明示的なファイル参照と固定 recipe を受け取ります。ユーザーコード、import、shell command、interpreter path は受け付けません。研究結果は RESEARCH-ONLY、`pit_guarantee=false` です。

R0 は capability、catalog、登録済みファイル／run／job、resource、明示選択された過去研究 Paper 口座の照会です。すべて読み取り専用です。R1 はローカル検証、分析、plan、因子／モデル／エンジン／指標研究、report 感度分析、broker preview、明示要求された broker 読み取り専用診断を行います。R1 は選択 workspace に task 成果物を書きますが、注文を送信しません。R2 mutation には server の `--enable-paper` と `agent_call_id`、`idempotency_key` の両方が必要です。過去研究 Paper の作成、step、run-all にはさらに呼び出しの `confirm_paper=true` が必要ですが、workspace draft には不要です。R3 の注文送信／取消 tool は予約済みで無効であり、有効 catalog に登録されません。

入力 path は必ず設定済み workspace 内に解決されます。呼び出しごとに厳密な JSON schema を検証し、永続 receipt を保存します。研究 task は stage／status、入力・ソース identity、ログ、完了または失敗 receipt を保持します。task directory 作成後に失敗した場合、失敗情報とともに workspace 相対 `task_ref` が返されるため、削除や再作成をせず調査に使えます。この値は任意の filesystem path ではありません。

```shell
kabuforge doctor
kabuforge demo --out output/agent_demo
kabuforge mcp --workspace output/agent_workspace
```

`kabuforge demo` は架空の合成 engineering fixture のみを作成します。実ローカル cache の course や市場データの証拠ではありません。MCP process は broker credential を読み込まず、起動時に broker へ接続しません。

<!-- section:risk -->
## Risk level と明示操作

| Level | 動作 | 条件 |
|---|---|---|
| R0 | 読み取り専用 inspection、capability、catalog、resource、status、過去研究 Paper の照会。 | mutation や cursor 進行なし。 |
| R1 | ローカル研究 task と plan、オフライン broker mapping、明示要求された localhost 読み取り専用診断。 | workspace と入力参照を明示。読み取り専用 GET には `confirm_read_only=true` が必要。参照／設定がない、または無効なら GET は送信しない。 |
| R2 | draft mutation と隔離された過去研究 Paper 口座の変更。 | server の `--enable-paper` と空でない `agent_call_id`、`idempotency_key`。過去研究 Paper の create／step／run-all には呼び出しの `confirm_paper=true` も必要。 |
| R3 | 外部への注文送信／取消。 | 予約済みで無効。呼び出せる tool はない。 |

オフライン broker mapping preview は呼び出しを行わない transport を使い、credential reference を解決しません。別の読み取り専用操作は明示的に呼び出されたときだけ設定済み参照を解決し、設定済み localhost API に cash、positions、orders の上限付き GET を送ります。環境変数参照がない場合は transport より前に失敗し、GET は 0 件です。報告やログは secret 値を表示しません。これは実 broker terminal や order book 接続の証拠ではありません。注文送信と取消はできません。

過去研究 Paper は、明示選択した凍結 bars manifest と、期待 SHA-256 に結び付いた完了済み strategy report から作る新規隔離口座です。専用の追加専用研究 journal を所有し、レガシー執行 ledger は開きません。`research_paper_query` は R0 で、cursor も journal も変更しません。step／run-all は R2 gate と冪等性を要求します。同じ identity の再送は既存結果を返し、イベントを重複追加しません。過去データ上の連続株数を使う研究 replay であり、forward Paper でも過去時点でのデータ利用可能性の証明でもありません。

```shell
kabuforge mcp --workspace output/agent_workspace --enable-paper
```

<!-- section:evidence -->
## 根拠と制約

transport は JSON-RPC 2.0 の `initialize`、`ping`、tools/resources の list と resource read を実装します。読み取り専用 resource は capability、因子／戦略 catalog、schema、run report、選択済みローカライズ文書です。R0/R1 は取引権限ではありません。R2 Paper opt-in は R3 を有効にしません。予約済み外部 hook が metadata に表示されても、R3 は無効のままです。

call ID と冪等キーは永続 protocol 入力ですが、不確実な結果確認の代わりにはなりません。応答状態が不明なら同じ call/task receipt を確認し、同じ identity を使ってください。新しい key で mutation を再送しないでください。credential は参照だけを使い、secret 値を tool 引数、recipe、task log、receipt に入れないでください。

同梱 `kabuforge demo` は架空 fixture を使用します。正式な local-cache course はユーザー所有の実過去データと別の source receipt を使い、bars や完全な report を package に含めません。過去結果は RESEARCH-ONLY／PIT false です。実端末接続、承認 workflow、注文送信、取消は確認されていません。
