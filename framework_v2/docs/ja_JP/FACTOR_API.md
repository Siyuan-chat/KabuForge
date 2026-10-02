---
doc_id: factor_api
version: 1
locale: ja_JP
---

# Factor API と拡張開発ガイド

[English](../en_US/FACTOR_API.md) · [简体中文](../zh_CN/FACTOR_API.md) · [日本語](../ja_JP/FACTOR_API.md)

本ガイドは、現在の v1 設定契約と公開 Python インターフェースを説明します。ファクターの追加はここから始め、結果をポートフォリオ判断に変換するには[Strategy API](STRATEGY_API.md)へ進んでください。将来のすべてのリリースとの互換性を保証するものではありません。

<!-- section:contract -->
## 1. 計算関数と検証関数を実装する

```python
from kabuforge.api import FactorContext, FactorResult, FactorSpec


def compute_factor(spec: FactorSpec, context: FactorContext) -> FactorResult:
    ...


def validate_factor(spec: FactorSpec) -> None:
    ...
```

上記はインターフェースのシグネチャであり、完成した実装ではありません。`BaseFactor` の継承は不要です。信頼されたアプリケーションコードが、実装 ID とバージョンを指定して呼び出し可能なオブジェクトを登録します。仕様が不正な場合、検証関数は例外を送出してください。戻り値は使用されません。通常の計画処理では `ApplicationService.validate()` が登録済み検証関数を実行し、計算結果には `FactorResult` が必要です。

ファクターは観測値やシグナルを計算し、注文を構築しません。ネットワーク接続、認証情報、ファイル書き込み、キャッシュ管理は計算処理の外に置いてください。登録は信頼境界であり、Python のサンドボックスではありません。信頼できるコードだけを読み込みます。

## 2. バージョン付き設定を定義する

実行可能なチュートリアルは、以下と同一の `factor.json` を生成します。

```json
{
  "schema_version": "1.0",
  "id": "price_change",
  "version": "1",
  "kind": "factor",
  "implementation": {
    "id": "example.price_change",
    "version": "1",
    "parameters": {
      "periods": 1
    }
  },
  "data_requirements": [
    {
      "dataset": "prices",
      "fields": [
        "code",
        "date",
        "close"
      ]
    }
  ],
  "lookback": 2,
  "output": {
    "name": "price_change",
    "description": "Synthetic trailing price change",
    "unit": "return"
  }
}
```

| フィールド | 意味と現在の制約 |
| --- | --- |
| `schema_version` | 設定スキーマのバージョン。現在は `"1.0"`。 |
| `id`, `version` | ファクター設定自体の識別子とバージョン。ID は戦略の計算式で使う変数名でもあります。 |
| `implementation.id`, `implementation.version` | 登録済みアルゴリズムの厳密な識別子。未知のバージョンは失敗し、自動的に代替しません。設定バージョンとは別です。 |
| `implementation.parameters` | アルゴリズム固有の設定。共通スキーマはオブジェクト型を要求し、意味上の検証は登録した検証関数が担当します。 |
| `data_requirements` | 必要なデータセットとフィールドの宣言。自動ダウンロード機能やデータ品質保証ではありません。 |
| `lookback` | 意味を実装側で定義する非負整数。本例では暦日ではなく `periods + 1` 個の観測値です。フレームワークはこの値でデータを自動切り詰めしません。 |
| `output` | 出力名、説明、任意の単位。単位ラベルは値を自動標準化しません。 |
| `metadata` | 任意の説明情報。認証情報やコードのインポート指示を含めてはいけません。 |

共通仕様は [factor.schema.json](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/schemas/factor.schema.json) にあり、未知のトップレベルフィールドを拒否します。`FactorSpec.from_config()` は不変の仕様を作成しますが、**完全な JSON Schema 検証の代わりにはなりません**。ファイルベースの実行には登録済みサービスの `validate(run_path)` を使用し、単独計算でも共通スキーマと固有の検証関数の両方を適用してください。

本例の検証関数は `periods` に 1–252 の整数を要求し、真偽値や余分なパラメーターを拒否します。フィールド宣言と参照期間も検証します。計算は「最後の可視終値 ÷ N 観測前の終値 − 1」です。履歴不足は欠損のままとし、存在しない取引日を補いません。

## 3. 判断時点で可視のデータだけを読む

```python
prices = context.read("prices", fields=("code", "date", "close"))
universe = context.universe()
```

`FactorContext` には、タイムゾーンを明示した `decision_at`、データセット名から DataFrame へのマッピング、空でない `data_snapshot_hash` を渡します。入力の各行にはタイムゾーン付き `available_at` が必要です。欠落やタイムゾーン未指定は拒否されます。読み取りでは締切時刻より後の行を除外し、`asof` を判断時刻より未来にはできません。既存の `date`、`asof_date`、`disclosed_date`、`data_end_date` も時間検査の対象ですが、元の値は保持されます。

`read(..., fields=...)` は `available_at` も返します。読み取り結果は毎回ディープコピーです。`universe()` は最新の可視グローバル・ユニバーススナップショットを選択し、`in_universe == True` を抽出して重複コードを拒否します。このデータセットには `asof_date`、`code`、`in_universe`、`available_at` が必要です。

宣言した時刻は、実際の過去の可視性の証明ではありません。取り込み側で公開時刻、改訂、コーポレートアクション、過去のユニバース構成を別途確認します。ダウンロード時刻で代用してはいけません。コンテキストへハッシュを渡すだけではバイト列は検証されません。本例はコンテキスト構築前に、ファイルのバイト列を検証済み実行のハッシュと照合します。

## 4. `FactorResult` を返す

`minimal` と `detail` の DataFrame、および `summary` マッピングを渡します。`minimal` には次の6列が必要です。

| 列 | 意味と検証 |
| --- | --- |
| `code` | この結果内で欠損がなく一意な銘柄識別子。 |
| `factor_name` | 欠損のない出力名。新規ファクターでは `spec.id` を利用できます。 |
| `factor_value` | 有限の数値または明示的な欠損値。無限大と不正な数値文字列は拒否します。 |
| `signal_date` | シグナル日。本例では判断時点の現地日付を設定します。 |
| `data_end_date` | 使用したデータの最終日。本例で履歴がない場合は欠損です。 |
| `rebalance_date` | 旧形式互換の日付メタデータ。注文のスケジュール指示ではありません。 |

1つの結果は横断面であり、同一コードが繰り返される複数日パネルではありません。日付列は必要ですが、コンストラクターは欠損日付を許容し、欠損でない解析不能な日付を拒否します。この許容は時点証拠の認証を意味しません。実装では実際の時刻と日付の意味を維持してください。

本例は `FactorResult(..., factor_id=spec.id, binding_id=spec.id)` を返します。`factor_id` は任意の `factor_name` 照合用、`binding_id` は設定上のファクター ID との結合用です。後者は旧 `factor_name` を維持するアダプターにも対応します。組み込み戦略は結合を検証するため、独自戦略でも同等の検査を維持してください。`from_legacy_dict()` / `to_legacy_dict()` は既存の `minimal/detail/summary` 形式に対応し、結果のアクセサーはコピーを返します。

## 5. 信頼された起動コードで登録する

```python
from kabuforge.api import ApplicationService
from examples.extension_demo import compute_price_change, validate_price_change

app = ApplicationService()
app.register_factor(
    "example.price_change", "1", compute_price_change, validate_price_change,
)
```

この断片はファクターのみを登録します。完全な例の `build_service()` はファクターと戦略の両方を登録します。設定は許可済み ID を選ぶだけで、任意の Python インポート、`eval`、未登録実装を要求できません。ID/バージョンの重複は失敗します。登録はこのサービスインスタンスに限定され、別の CLI、GUI、MCP プロセスが例を自動検出したりレジストリーを共有したりはしません。

## 6. 完全なオフライン例を実行する

Python 3.12+ を使用し、ソースチェックアウトのルートで実行します。

```shell
python -m pip install -e .
python examples/extension_demo.py --out output/extension_demo
python -m unittest discover -s framework_v2/tests -p test_extension_example.py -v
```

出力先には新しいディレクトリを指定します。既存ディレクトリは上書きしません。`--out` を省略すると一時ディレクトリを使います。[extension_demo.py](https://github.com/Siyuan-chat/KabuForge/blob/main/examples/extension_demo.py) はファクター、戦略、実行、スナップショット、口座の JSON を作成し、設定参照グラフを検証して計算後に `ApplicationService.plan()` を呼び出します。

架空銘柄 `SYN_A` は100から110へ、`SYN_B` は100から95へ変化します。意図的に追加した未来の `SYN_B` 価格は見えません。戦略は `SYN_A` を要求し、注文計画前に銘柄上限が元の比率1を0.5へ制限します。出力には `synthetic: true` と `orders_submitted: false` を明記します。注文実行、約定、執行台帳への書き込み、過去収益評価、証券会社への接続は行いません。

<!-- section:evidence -->
## 7. 検証、診断、トラブルシューティング

[実行可能なチュートリアルテスト](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/tests/test_extension_example.py) は、アプリケーション経路、CLI、上書き防止、未来行の分離、不正時刻・パラメーター、不正・重複価格、履歴不足、登録失敗、結果検証、判断状態の意味を確認します。3言語の JSON ブロックを実行可能な設定ファクトリーと照合し、記述のずれを検出します。

| 症状 | 確認すること |
| --- | --- |
| 未知の実装 | 設定を検証・実行する同一サービスに厳密な ID/バージョンを登録します。 |
| 仕様・参照期間の不正 | 共通スキーマと実装の検証関数を実行し、不正設定を黙って変換しません。 |
| `available_at` やタイムゾーンの欠落 | 取り込み時の証拠を修復し、検査通過のための過去時刻を捏造しません。 |
| コード・観測の重複 | データ粒度と改訂処理方針を先に確定します。 |
| ファクター値の欠損 | 可視履歴を用意するか、戦略の `reject` / `drop` 方針を明示します。 |
| 結合識別子の不一致 | 設定 ID と `binding_id` を一致させ、旧名称は明示的アダプターで維持します。 |

キャッシュキーは設定、実装識別子、スナップショットハッシュ、ユニバース識別子、判断時刻を結合します。`FactorSpec.cache_key()` は識別子を計算するだけでキャッシュを読み書きしません。`list_factors`、`describe_factor`、`validate_factor`、`analyze_factor` は agent 向けの一覧・検証・診断ツールであり、各ファクターが実装するメソッドではありません。分析は網羅率、欠損、分布、順位、分位点、最大データ経過時間を示しますが、`research_readiness: NOT_EVALUATED` を返し、予測能力を証明しません。

正確な仕様は[ファクター契約](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/factors.py)、[アプリケーションサービス](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/application.py)、[設定解決](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/config.py)を参照してください。続いて[Strategy API](STRATEGY_API.md)と[研究方法](RESEARCH_METHODOLOGY.md)をご覧ください。
