# Starter evaluation targets

Checked 2026-09-13. Only the first target is bundled. Public targets below are
candidates, not evaluated recommendations; select and inspect a pinned version and
its license before use. Do not auto-download or execute them merely from this list.

| Target | Useful check | Prerequisites / current limit |
| --- | --- | --- |
| Bundled `examples/file-skill` (`file-summary`) | UTF-8 line/word counts, empty input and missing files; output is `summary.json` | First example to use when the user has no target. Copy into a fresh local workspace; no external service fixture. Real model execution still needs the user's provider and limits. |
| [Anthropic skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator) | Producing and revising skill files against fixed requirements | Start with a constrained local drafting case. Its broader evaluation workflow can invoke other agents; do not assume those calls are metered. |
| [Anthropic webapp-testing](https://github.com/anthropics/skills/tree/main/skills/webapp-testing) | Local browser behavior, selectors and generated test scripts | Playwright and a resettable local app are needed. External fixture support remains a release gate. |
| [OpenAI gh-address-comments](https://github.com/openai/skills/tree/main/skills/.curated/gh-address-comments) | Review-comment handling and resulting code changes | Needs a disposable repository/PR and controlled GitHub access. Do not run against a production PR. The reference repository is deprecated; pin and inspect it rather than treating it as current installation guidance. |

A useful first progression is bundled local files, then a selected public local
skill, then browser/external-service workflows after fixture support exists. This
is an evaluation order based on reproducibility, not a performance ranking.
