# 0.2.0 development preview

The skill now offers current environment improvement (recommended) and optional
API model comparison. Current execution uses existing native login/model settings
for steps and structure optimization without new API setup. It preserves the
active conversation's connection and runs evaluations in local isolated copies.
The skill asks for mode, repetitions (3 recommended) and time before execution;
provider/key/model setup and a USD ceiling appear only for API comparison.

Current reports use native-reported input/output counters, with cache and reasoning
subsets counted once. Missing usage and dollars stay unknown. Quality must pass,
time or reported tokens must improve, and the other known metric cannot worsen.
Existing account billing/quotas apply; no dollar ceiling or savings claim is made.
API experiments retain gateway metering, mandatory USD/time limits, and promotion
requiring lower measured cost and shorter completion time.

Migration: `optimize` now defaults to `--execution current`. Existing API scripts
must add `--execution api`; passing a USD ceiling to current execution is rejected.
Replay profiles record their execution path; older profiles retain API behavior.
Authentication/transport errors with missing artifacts remain unverified and
retryable instead of becoming cached quality failures.

Validation: 59 standard-library tests cover current optimization/replay without
provider discovery or gateways, metric promotion, credential preservation, native
usage parsing, error classification and existing API flows. Both actual CLIs pass
eight text/file-tool scenarios against loopback fake providers (twelve requests):
Claude Code 2.1.263, Codex CLI 0.154.0, LiteLLM 1.100.1. No paid providers or real
subscription/keychain credentials were used. Keychain-only native authentication
in copied configuration remains unverified, as do paid compatibility and external
hook/MCP fixtures. OpenCode then Pi remain planned adapters.

---

# 0.1.2 development preview

Provider setup and target selection now live in the skill. Users are guided through
provider/key configuration, baseline model/effort, mode, repetitions and explicit
budget/time limits when they actually start an evaluation.

`harness-opt configure` creates or updates a private .env without API calls. Keys
come from a named environment variable or hidden local terminal input, never a
command-line secret argument. Existing settings are preserved, updates are atomic,
and configured does not imply authenticated or measured.

The file-summary demo is now bundled inside the installed plugin, with a shortlist
of public target candidates. Public skill discovery excludes nested examples, so
bundled demonstrations are not mistaken for additional plugin entrypoints.

Execution code, baseline defaults/capture rules and evaluation definitions remain
inside the plugin; private credentials and results remain outside distribution.
OpenCode then Pi are the user-selected next adapter priorities. Existing adapters
are still Claude Code and Codex; direct-API-only skill validation is not implemented.

Validation: 48 tests, including credential round trips, preservation, private file
permissions, noninteractive secret-input rejection and public-entrypoint discovery.
Paid model comparisons and external hook/MCP fixtures remain unverified.

---

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
