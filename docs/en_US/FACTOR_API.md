---
doc_id: factor_api
version: 1
locale: en_US
---

# Factor API

<!-- section:contract -->
## Contract

Factors are selected by implementation ID and version from an allow-listed registry. A factor implementation receives a `FactorSpec` and `FactorContext` and must return `FactorResult`; a registered validator checks the spec before computation. Dynamic import, evaluation, and unvalidated implementation selection are prohibited.

The factor cache key binds implementation parameters, data snapshot hash, universe identity, and decision time. A cache hit therefore remains tied to a declared research context, not merely a factor name.

<!-- section:evidence -->
## Evidence

`list_factors`, `describe_factor`, `validate_factor`, and `analyze_factor` expose catalog, validation, and descriptive diagnostics. Analysis reports coverage, missing values, distribution, ranks, quantiles, and maximum data age; it reports `research_readiness: NOT_EVALUATED`.
