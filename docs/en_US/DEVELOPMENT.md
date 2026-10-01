---
doc_id: development
version: 1
locale: en_US
---

# Development

<!-- section:contract -->
## Contract

Develop against the package boundary, not against GUI internals or configuration-driven imports. Register trusted factor code with `ApplicationService.register_factor(id, version, function, validator)` and trusted strategies with `StrategyRegistry.register(StrategySpec, factory)`. Validators are mandatory; duplicate identities are rejected.

Use deterministic local fixtures. Keep research data, credentials, broker transports, and private implementations outside a public distribution. Do not treat a simulated fill, a planned intent, or a CLI success exit as proof of live execution.

<!-- section:evidence -->
## Evidence

The public package is `kabuforge`, requires Python 3.12+, and retains the repository MIT license. Its command entry point is `kabuforge = kabuforge.cli:main`. Public source provenance is pinned by `public_source_manifest.json` and checked for source, wheel and sdist.
