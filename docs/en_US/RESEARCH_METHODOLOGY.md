---
doc_id: research_methodology
version: 1
locale: en_US
---

# Research Methodology

<!-- section:contract -->
## Contract

Research inputs must declare a decision time and snapshot identity. `check_point_in_time` and `check_lookahead` inspect visibility using `available_at`; rows later than the decision timestamp are counted and must be gated by the point-in-time context. Missing availability timestamps make a dataset invalid for this check.

`check_lookahead` is an available-at gate only. It is not a full scientific certification of provenance, vendor timing, historical revisions, survivorship, corporate actions, universe construction, or economic validity.

<!-- section:evidence -->
## Evidence

Diagnostics return `decision_at`, per-dataset row counts, missing timestamps, future rows, visible rows, validity, and `future_rows_require_gate`. Factor diagnostics describe a supplied result; they do not establish out-of-sample performance or investability.
