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
