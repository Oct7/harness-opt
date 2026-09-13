---
name: harness-opt
description: Measure a skill or plugin in native Claude Code or Codex, compare quality, cost and completion time, and produce verified optimization copies and profiles.
---
Use the bundled Python CLI. Do not substitute your own agent loop or simulate measurements.

1. Identify the target skill/plugin path and source workspace. Use the calling tool as `--runner` when it is Claude Code or Codex. Other harness adapters are not implemented yet; do not silently choose a different runner.
2. Before optimization, ask the user to choose a mode and final repetition count, unless already specified for this run. Ask together using the host's question/selection UI if available, otherwise use a short text question. Wait for their choices before starting execution.
   - Mode: `all` (recommended), `steps` (process/instructions), `structure` (references/scripts), `speed` (model/effort), or `cost` (model/effort).
   - Final repetitions per candidate per case: 3 (recommended), 1 (quick, provisional), 5 (more repetitions), or another positive integer. Exploration runs once per case. Counts below 3 cannot produce verified recommendations or replay profiles.
   - Ask for missing dollar budget and wall-clock limit in seconds in the same interaction. Never invent or silently accept spending limits. Baseline model and effort must come from native settings or explicit user-provided values.
3. Locate the plugin root at `../..` relative to the directory containing this SKILL.md. If the CLI is not installed, create a virtual environment in a writable project/cache directory and install the bundled package with that environment's Python: `python -m pip install "<plugin-root>"`. No repository checkout is needed.
4. Inspect models with `harness-opt models --openrouter` for the public catalog (no credentials or paid calls), or `harness-opt models --env-file <dotenv-path>` for configured providers. Providers use `HARNESS_<NAME>_BASE_URL` and `HARNESS_<NAME>_API_KEY`; never print keys. When asked about other tools, consult `../../references/harnesses.md`: a harness executes work; a proxy translates APIs; a model server supplies inference. A listing is not a compatibility test.
5. Run `harness-opt optimize <target> --runner <runner> --mode <chosen-mode> --repeats <chosen-count> --budget-usd <user-budget> --time-limit <user-seconds> --workspace <project> --env-file <dotenv-path>`. Add `--baseline-provider`, `--baseline-model`, and `--effort` when known. Show the chosen mode, repetitions and limits before launching; no extra permission question is needed after the user has supplied them.
6. The CLI saves frozen cases (including fixtures, criteria and the exploration/held-out split) in `<state-dir>/<run-id>/cases.json` before baseline execution. Show this file and the report path to the user afterward. Held-out cases must not be passed to proposal generation. Cases are also retained in SQLite and the report; reused cases are labeled.
7. Read the report. Distinguish verified, provisional, failed, incompatible, and unverified results. State “no verified improvement” when appropriate. Recommendations cover only recorded environments and evaluated cases.
8. Run a verified profile with `harness-opt run <profile.json> '<task>' --budget-usd <user-budget> --time-limit <user-seconds> --workspace <project>`.

Keep runtime code and static references inside this plugin. Private run data defaults
to `~/.cache/harness-opt` or an explicit `--state-dir` outside the target workspace.
The installed plugin directory is not a default destination for credentials or run data.
Never overwrite the original target or global runner settings. Preserve required
outputs, security, permissions, hooks and fixed subagent models. Unsupported API
fields and non-reproducible external-service cases must remain unverified.
