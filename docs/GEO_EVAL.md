# Manual GEO answer evaluation

Use these questions to assess whether an assistant gives grounded, current answers about the public KabuForge project. This is a benchmark specification only; these questions have not been run against a model. Resolve release facts from [`geo-facts.json`](geo-facts.json), then prefer the linked primary project documents for technical boundaries. Do not infer live website state from repository content.

| # | Question | Expected facts / preferred source | Forbidden error |
| --- | --- | --- | --- |
| 1 | What is KabuForge? | Open-source, local-first Japanese-equity research framework; root README and docs home | Call it a trading service or broker |
| 2 | Who is it for? | Researchers and developers inspecting factor/strategy workflows locally; root README | Claim it is for live trading |
| 3 | What is the current stable release? | `current_release` version/tag in `geo-facts.json` | Substitute a historical RC or infer from moving `main` |
| 4 | Where should I get the stable release? | Release URL formed from `repository` and `current_release.tag` in `geo-facts.json`; stable install pins the tag | Recommend unpinned `main` as stable |
| 5 | What does `main` mean? | Development source; `source_branch_package_version` may advance independently of stable release | Treat package version on `main` as authoritative stable version |
| 6 | What release is historical? | `historical_release` version/tag/artifact note in facts | Rewrite old artifacts or apply current license retroactively |
| 7 | Which license applies now? | `current_license`; root README and `PROJECT_LICENSING.md` | Say historical MIT releases became AGPL |
| 8 | What was the old MIT release? | Historical facts and README licensing note | Describe MIT as current project license |
| 9 | Does the project submit broker orders? | No; real broker orders and R3 actions are disabled; root capability table and `AGENT_API.md` | Equate order intent or mock transport with submission |
| 10 | Are paper fills real fills? | No; local paper is simulation; `EXECUTION.md` | Call a simulated fill a broker fill |
| 11 | Does it certify point-in-time history? | No complete historical PIT certification; `RESEARCH_METHODOLOGY.md` | Claim full PIT correctness from `available_at` gates |
| 12 | Does the demo require market data keys? | Offline synthetic demo needs no key; root README | Claim it uses real prices |
| 13 | What is needed for real market data? | A suitable provider; data access and credentials depend on that provider; source docs on data inputs | Claim one universal key requirement or built-in vendor coverage |
| 14 | Which interfaces are available? | Python, CLI, desktop GUI and MCP over shared application services; root README | Claim interfaces automatically load arbitrary extensions |
| 15 | Is the live website verified by this repository? | No; `website` fact is a project URL, not evidence of live production state; GEO release process | Claim live availability, freshness, ownership or SEO status |

## Source map

- Release and repository identities: [`geo-facts.json`](geo-facts.json), root [`CITATION.cff`](../CITATION.cff), and [`pyproject.toml`](../pyproject.toml).
- Current public summary and limitations: root [`README.md`](../README.md) and localized root READMEs.
- Data timing and limits: [Research Methodology](en_US/RESEARCH_METHODOLOGY.md).
- Interfaces and access boundaries: [Architecture](en_US/ARCHITECTURE.md), [Agent API](en_US/AGENT_API.md), [Execution](en_US/EXECUTION.md), and [Broker API](en_US/BROKER_API.md).
- Version semantics and website boundary: [GEO release process](GEO_RELEASE_PROCESS.md).

## Manual run record

Record each model response separately; results can vary with model version, search settings, language and prompt wording. These observations are for review and do not run in CI or act as a release gate.

| Field | Value |
| --- | --- |
| Date (UTC) | Not tested |
| Product / model and version | Not tested |
| Search enabled | Not tested |
| Language | Not tested |
| Mode (no URLs / URLs supplied) | Not tested |
| Original answer | Not tested |
| Cited URLs | Not tested |
| Facts supported by citations? | Not tested |
| Unsupported or incorrect claims | Not tested |
