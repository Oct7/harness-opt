# Implementation record

Intent: implement the supplied harness-opt plan in this previously empty repository.
Python 3.11+, native Claude Code/Codex execution, LiteLLM protocol conversion,
SQLite records, mandatory explicit time and money limits, isolated copies, four
optimization modes, conservative quality gates, portable dual-plugin packaging.

| Work | Producer → consumer | Constraint |
| --- | --- | --- |
| Provider/gateway/budget | model metadata and metered native endpoint → optimizer | Unknown price/compatibility fails closed |
| Runner | frozen profile, fresh workspace, native output → optimizer | Never replace native agent loop |
| Evaluation/store | fixed cases, verdicts, resumable records → CLI | No unverified recommendation |
| Packaging/CLI | installed plugin → bundled runtime | No repo-relative runtime dependency |

Implementation decisions:
- Initialize a new `implementation` branch: there was no pre-existing repository or worktree.
- Public GitHub publication requires a destination; prepare distributable files locally.
- Real paid integration runs require a user-supplied budget; no paid calls are authorized by this implementation request alone.
- Reference pattern descriptions are original summaries, not redistributed source files. Pin provenance commits and retain per-file licensing notices. The pinned OpenAI skills README marks that repository deprecated.

Verification results and remaining release gates are recorded in README.md.

Completed verification: 40 unit/integration checks from a clean wheel installation;
four real native CLI text/file-tool scenarios through loopback providers; both
marketplace install workflows. Public repository authorized by user and created at
https://github.com/Oct7/harness-opt. Publish as development preview: paid provider
quality checks and external fixture support remain explicit stable-release gates.
