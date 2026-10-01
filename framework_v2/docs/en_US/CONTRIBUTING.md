---
doc_id: contributing
version: 1
locale: en_US
---

# Contributing

<!-- section:contract -->
## Contract

Contributions must preserve local-first and no-live-trading boundaries. Add tests for validation, registry identity, workspace containment, idempotency, and failure states when changing those contracts. Keep GUI guidance in the existing manuals; do not rewrite it while documenting the package API.

New public factor or strategy work requires an independently implementable version, validator, fixtures, provenance description, and review of information timing. Never contribute private factor code or credentials to a public artifact.

<!-- section:evidence -->
## Evidence

Before review, exercise affected CLI commands, run relevant tests and verify the public distribution boundary. New implementations require review; do not weaken the provenance, credential or private-code gates.

New contributions to project-owned code, documentation and assets are submitted under AGPL-3.0-only. Preserve third-party notices and contribute only material you have the right to license. No additional CLA is introduced.
