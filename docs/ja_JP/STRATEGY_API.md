---
doc_id: strategy_api
version: 1
locale: ja_JP
---

# Strategy API と拡張開発ガイド

[English](../en_US/STRATEGY_API.md) · [简体中文](../zh_CN/STRATEGY_API.md) · [日本語](../ja_JP/STRATEGY_API.md)

先に [Factor API](FACTOR_API.md) を参照してください。本ガイドは現在の戦略登録契約を説明するもので、証券会社の執行 API ではありません。共通経路は Factor → StrategyDecision → TargetPortfolio → RiskPolicy → Planner → OrderIntent です。

<!-- section:contract -->
## 1. 登録用の判断契約を実装する

```python
from typing import Mapping, Protocol
from kabuforge.api import FactorContext, FactorResult, StrategyDecision, StrategyState


class Strategy(Protocol):
    def decide(
        self, *, results: Mapping[str, FactorResult], context: FactorContext,
        state: StrategyState, decision_identity: str, rebalance: bool = True,
    ) -> StrategyDecision:
        ...
```

上記はインターフェースのシグネチャです。ファクトリーは `(config, factor_ids)` を受け取り、`decide` を持つオブジェクトを返します。クラスのコンストラクターでも構いません。特定の基底クラスの継承ではなく、構造的な契約で判定します。ファクトリーは対応できない設定を拒否してください。登録は信頼されたアプリケーションコードが行い、設定から任意コードをインポートすることはできません。

| 入力 | 意味 |
| --- | --- |
| `results` | 設定上のファクター ID から検証済み `FactorResult` へのマッピング。キーは実装 ID ではありません。 |
| `context` | 読み取り専用の時点データと現在の判断時刻。 |
| `state` | 前回判断の明示的状態、または初期 `StrategyState()`。 |
| `decision_identity` | 今回の判断識別子。組み込みアダプターは直前の識別子の再処理を拒否します。独自実装でも同等の検査を維持します。 |
| `rebalance` | 今回、新しい目標を要求するか。既定値は `True`。 |

**互換性上の注意：** `framework_v2.strategy.CompositeFactorStrategy.decide()` は `(target, state)` を返し、登録契約の結果オブジェクトではありません。`CompositeFactorStrategyAdapter` を使うと、`decide()` が `decide_with_audit()` を呼び出して `StrategyDecision` を返します。本例はこのアダプターにより、結合、日付、欠損、計算式、重複判断の検査を維持します。

## 2. 注文ではなく完全な判断を返す

`StrategyDecision` には9つのフィールドすべてが必要です。

| フィールド | 目的 |
| --- | --- |
| `target` | 完全な `TargetPortfolio`、またはリバランスなしを示す `None`。 |
| `state` | 次の判断へ渡す新しい `StrategyState`。 |
| `scores` | コードごとの有限なスコア。 |
| `ranked_codes`, `dropped_codes` | 決定的な順位と明示的な除外コード。 |
| `preprocess`, `missing_policy` | 実際に使用した処理方針。 |
| `factor_inputs`, `factor_processed` | 検査用のファクター別・コード別の入力値と処理後の値。 |

独立した非スコア型戦略では、意味上妥当なら監査マッピングを空にできますが、契約は正確に埋めてください。スコアや証拠を作り上げてはいけません。これによって現在のファイルスキーマのスコア設定要件がなくなるわけではありません。

```python
from kabuforge.api import TargetPortfolio

no_rebalance = None
liquidate_to_cash = TargetPortfolio.from_weights({})
full_target = TargetPortfolio.from_weights({"SYN_A": "0.5"})
```

3つの値の意味は異なります。`None` はリバランスを要求せず、現状の配分を維持します。空の目標は現金への全決済を要求します。空でない目標は追加購入指示ではなく**望ましいポートフォリオ全体**であり、記載されていない既存銘柄はゼロを目標とします。全決済要求はリスク制約や計画処理により制限され、部分的にしか実現できない場合があります。

比率には有限の `Decimal` を使用します。`TargetPortfolio.cash_residual` は `1 - long_gross` であり、口座の実際の現金でも `1 - net` でもありません。目標型で負の比率を表現できても、実際の空売りや本番証券会社接続が利用可能とは限りません。

`StrategyState` は `last_decision_identity`、`regime`、`cooldown_until`、JSON 互換の `transition_state` を持ち、`to_json()` / `from_json()` で明示的に永続化できます。フィールドの存在だけでレジーム判定やクールダウン処理は実装されません。アプリケーションは計画ごとにファクトリーで戦略を作成するため、インスタンス内の可変状態が判断をまたいで残ることに依存しないでください。

## 3. 戦略設定を定義する

本例は以下と同一の `strategy.json` を生成します。

```json
{
  "schema_version": "1.0",
  "id": "extension_demo",
  "version": "1",
  "kind": "strategy",
  "implementation": {
    "id": "example.positive_score",
    "version": "1"
  },
  "universe": {
    "snapshot": "universe"
  },
  "factors": [
    "factor.json"
  ],
  "scoring": {
    "formula": "price_change"
  },
  "portfolio": {
    "construction": "equal_weight",
    "parameters": {
      "top_n": 1,
      "preprocess": "none",
      "missing_policy": "reject"
    }
  },
  "risk": {
    "max_position_weight": 0.5,
    "max_gross_exposure": 1,
    "turnover_budget": 2,
    "allow_short": false
  },
  "rebalance": {
    "frequency": "daily"
  }
}
```

`factors` は戦略ファイルからの相対パスです。`scoring.formula` が使うのは**ファクター設定内の ID**であり、本例では `price_change` です。`factor.json` や `example.price_change` ではありません。解決処理は計画前に run → strategy → factors 全体の参照グラフと内容識別子を検証します。

`implementation` は登録済み戦略を選択します。v1 設定で省略すると、`composite_factor` バージョン `"1"` だけを選択します。設定自身の `version` は実装バージョンではありません。スキーマにはユニバースのパス形式もありますが、現在のアプリケーション計画経路では `universe: {"snapshot": "universe"}` が必要です。

### 組み込み合成戦略の動作

アダプターはファクター ID、有限定数、`+`、`-`、`*`、`/`、単項符号を扱います。関数呼び出し、属性参照、インデックス操作、任意の評価はできません。前処理は `none`、`zscore`、`rank`、欠損処理は明示的に `reject` または `drop` を選びます。候補はユニバースと全参照ファクターの非欠損コードの共通部分です。同点はコード順で決定します。

上位をロング、残りの下位をショートに選択し、各側を等ウェイトと明示的グロス配分で構築します。`portfolio.construction: "rank"` は現在、等ウェイト構築の別名であり、**順位比例の配分ではありません**。ショート目標は後段の執行能力の制約を受けます。

### 現在の拡張範囲

独自ファクトリーの選択は独自設定スキーマを作りません。[strategy.schema.json](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/schemas/strategy.schema.json) は引き続きファクター、計算式、ポートフォリオ、リスク、リバランスの各設定を要求し、パラメーター名を制限します。解決処理も計算式を検証します。ファクターを持たないイベント戦略や新しい最適化パラメーター群には、将来の明示的なスキーマ・統合変更が必要です。未定義 JSON フィールドでは実現できません。

スキーマは daily、weekly、monthly の設定を認識しますが、`ApplicationService.plan()` 自身はそのカレンダーを評価せず、既定の `rebalance=True` で `decide` を呼びます。頻度の宣言は呼び出し側がそれを守る証明ではありません。適切な呼び出し側または明示的に実装した戦略ロジックで実際のスケジュールを適用し、その経路をテストしてください。

## 4. 信頼されたファクトリーを登録する

```python
from kabuforge.api import ApplicationService, StrategyRegistry, StrategySpec
from examples.extension_demo import PositiveScoreStrategy

registry = StrategyRegistry()
registry.register(
    StrategySpec("example.positive_score", "1"), PositiveScoreStrategy,
)
app = ApplicationService(strategy_registry=registry)
```

これは戦略だけを登録します。実行設定の検証前に、同じアプリケーションサービスへ必要なファクターも登録してください。`examples/extension_demo.py:build_service()` が両方の登録を示します。未知・重複の識別子は失敗し、一覧は実装 ID とバージョン順に並びます。レジストリーはサービスのメモリー内に限られます。パッケージのエントリーポイントを追加せず、別 CLI・GUI・MCP プロセスに自動ロードされることもありません。利用するフロントエンドに同じ信頼された初期登録処理を組み込みます。

例の `PositiveScoreStrategy` はスコア計算をアダプターへ委譲し、正の処理後スコアが1つもなければ空の現金目標を要求します。`dataclasses.replace` により監査情報と新しい状態を維持し、リバランスなしの場合は `target=None` を保ちます。ショート選択は拒否します。これは教材用方針であり、検証済み投資戦略ではありません。

## 5. 実行設定と計画境界へ接続する

本例の `run.json` は次のとおりです。

```json
{
  "schema_version": "1.0",
  "id": "extension_demo_run",
  "version": "1",
  "kind": "run",
  "strategy": "strategy.json",
  "data_snapshot": "snapshot.json",
  "clock": {
    "start": "2024-05-01",
    "end": "2024-05-01",
    "timezone": "Asia/Tokyo"
  },
  "mode": "fake",
  "fees": {
    "commission_rate": 0,
    "minimum_fee": 0
  },
  "account_ref": "account.json",
  "output_dir": "output"
}
```

同じディレクトリに `factor.json`、`strategy.json`、`snapshot.json`、`account.json` を生成します。各パスは参照を記述したファイルからの相対パスです。ゼロ手数料、口座、価格は合成例であり、現実の執行条件ではありません。

`app.validate(run_path)` が設定を解決・検証します。その後 `app.plan(...)` へ解決済み実行、識別子が一致する `FactorContext`、`AccountState`、別々の研究用参照価格と執行気配、銘柄情報、タイムゾーン付き `now`、任意の前回状態・能力宣言を渡します。戻り値の `RunResult` にはファクター結果、判断、リスク判断、注文計画が含まれます。サービス自体は注文を送信せず、執行台帳にも書き込みません。

研究用参照価格は判断スナップショットに属します。後続の執行気配は計画を制約できますが、過去の研究目標を遡って選び直してはいけません。戦略の後にリスク方針を適用し、売買単位、価格、現金などの計画検査を行います。計画の成功は約定ではありません。

Python 3.12+ を使用し、ソースチェックアウトのルートで実行します。

```shell
python -m pip install -e .
python examples/extension_demo.py --out output/extension_demo
python -m unittest discover -s framework_v2/tests -p test_extension_example.py -v
```

新しい出力ディレクトリを使うか、`--out` を省略して一時ディレクトリを使います。1回の判断を実行し、元の目標、許可後目標、リスク理由、計画注文数と `orders_submitted: false` を出力します。過去バックテスト、模擬約定、実取引ではありません。

<!-- section:evidence -->
## 6. テスト、一覧、トラブルシューティング

完全な実装は [extension_demo.py](https://github.com/Siyuan-chat/KabuForge/blob/main/examples/extension_demo.py) を参照してください。[test_extension_example.py](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/tests/test_extension_example.py) は登録済みアプリケーション経路、CLI、欠損処理、未来入力・結果、リバランスなしと全決済、重複判断、状態シリアライズ、3言語の設定例を検証します。既存 CI の探索対象となるため、ワークフローへ新しいテストコマンドを追加する必要はありません。

| 症状 | 確認すること |
| --- | --- |
| 未知の戦略 | 現在のサービスへ厳密な実装 ID/バージョンを登録します。 |
| 判断ではなくタプルが返る | 旧 `decide()` 簡略形ではなく登録用アダプター契約を使用します。 |
| JSON パラメーターが未対応 | 既存スキーマを守ります。登録はスキーマ拡張ではありません。 |
| 重複判断 | 戻り値の状態を引き継ぎ、永続化します。同一識別子を黙って再処理しません。 |
| 意図しない全決済 | 空目標を `None` の代わりに使わないでください。意味は意図的に異なります。 |
| 要求目標と許可後目標の相違 | 執行価格で研究シグナルを書き換えず、`RunResult.risk` と計画理由を確認します。 |
| 別プロセスに独自戦略がない | そのフロントエンドへ信頼された初期登録処理を組み込みます。登録はグローバルではありません。 |

`list_strategies` と `describe_strategy` は一覧情報を提供し、`plan_strategy` は計画前に実行設定と執行参照を検証します。これらは agent ツールであり、戦略プロトコルのメソッドではありません。任意コードのロードや実注文の権限を与えません。正確な仕様は[戦略レジストリー](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/strategy_registry.py)、[判断モデル](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/models.py)、[組み込み戦略とリスク](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/strategy.py)、[アプリケーションサービス](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/application.py)を参照してください。[執行](EXECUTION.md)と [Agent API](AGENT_API.md)もご覧ください。
