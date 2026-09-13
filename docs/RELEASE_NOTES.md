# 0.1.1 development preview

The skill now asks for an optimization mode and final repetition count before
execution, reusing choices already provided by the user. Three repetitions are
recommended. `optimize --repeats N` controls final executions per candidate per
case; values below three produce provisional candidates without verified profiles.

Frozen cases, fixtures, evaluation criteria and the exploration/held-out split are
saved in a separate `cases.json` before baseline execution, linked from the report.
Reports record the chosen mode/count and whether cases were reused.

The plugin now bundles a primary-source survey of OpenCode, Gemini CLI, Pi, Aider,
Cline, Copilot CLI, opencodex, LiteLLM and Ollama. This is documentation of candidate
integrations; native adapters remain Claude Code and Codex. Runtime code and static
references remain self-contained in the plugin. Private run data remains outside
the target workspace.

Validation: 43 unit/integration tests, including selected five-repeat execution,
one-repeat provisional results, invalid count rejection and persisted held-out cases.
Paid-provider quality verification and external hook/MCP fixtures remain pending.

---

# 0.1.0 development preview

Native Claude Code/Codex skill evaluation with `models`, `optimize`, `report`, and
`run`; four optimization modes; OpenRouter public price discovery; metered local
gateway; mandatory cost/time ceilings; SQLite failure reuse and budget journaling;
blinded evaluation and repeated confirmation; isolated copies, diffs, and replay
profiles. Both marketplace manifests and a self-contained plugin are included.

Verified locally on macOS with Python 3.14.5, LiteLLM 1.100.1, Claude Code 2.1.263,
and Codex CLI 0.154.0:

- 40 standard-library unit/integration tests pass from a clean wheel installation.
- Both native CLIs complete text and file-tool scenarios against loopback providers:
  four scenarios, six provider requests, real usage/stream timing capture.
- Both native marketplace installation workflows succeed in isolated user homes.
- The public OpenRouter catalog returned 445 models; 440 had token prices.

This is a prerelease, not full completion of all stable-release gates. Paid model
quality/cost comparisons have not been run. Hook/MCP optimization is blocked until
external fixtures can be verified; no fixture-approval CLI is provided. Session-only
settings are not recovered automatically. Unsupported protocol fields, reasoning,
hosted/media tools, alternate subagent providers, symlinks and linked worktrees fail
explicitly. Recommendations cover only recorded environments and generated cases.

Install from either marketplace with `Oct7/harness-opt`; see README for runtime
setup and budget arguments. The plugin archive is self-contained; the wheel is the
standalone Python CLI runtime. MIT license.
