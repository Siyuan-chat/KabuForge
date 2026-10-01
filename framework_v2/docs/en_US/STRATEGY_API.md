---
doc_id: strategy_api
version: 1
locale: en_US
---

# Strategy API

<!-- section:contract -->
## Contract

`StrategyRegistry` maps `StrategySpec(implementation_id, implementation_version)` to trusted factories. A factory accepts the strategy configuration and factor IDs and must return a `Strategy` implementing `decide`. Unknown and duplicate identities fail. The v1 configuration without an `implementation` field resolves only to `composite_factor` version `1`.

Decision code receives factor results, point-in-time context, strategy state, and a decision identity. It returns a decision; execution constraints and order construction are applied afterwards by risk policy and planner.

<!-- section:evidence -->
## Evidence

`list_strategies` returns registered identities and `describe_strategy` describes an approved selection. `plan_strategy` validates run and execution references before planning. Strategy catalog output is stable by implementation ID then version.
