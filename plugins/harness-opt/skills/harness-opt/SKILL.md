---
name: harness-opt
description: Measure a skill or plugin in native Claude Code or Codex, compare quality, cost and completion time, and produce verified optimization copies and profiles.
---
Use the bundled Python CLI. Do not substitute your own agent loop or simulate measurements.

1. Identify the target skill/plugin path. Use the calling tool as `--runner` (`claude` or `codex`). Default `--mode all`.
2. The user must specify a dollar budget and wall-clock limit in seconds before paid execution. Ask for missing values; never invent them. Baseline model and effort must come from the current native settings or explicit user-provided values.
3. Locate the plugin root at `../..` relative to the directory containing this SKILL.md. If the CLI is not installed, create a local virtual environment in a writable user-selected project/cache directory and run `python3 -m pip install "<plugin-root>"` with that environment's Python. The whole Python package is bundled; no repository checkout is needed.
4. The public OpenRouter price table is available with `harness-opt models --openrouter`, without credentials or paid calls. Discover configured models using `harness-opt models --env-file <dotenv-path>`. Providers use `HARNESS_<NAME>_BASE_URL` and `HARNESS_<NAME>_API_KEY`; never print API keys.
5. Run `harness-opt optimize <target> --runner <caller> --mode all --budget-usd <user-budget> --time-limit <user-seconds> --workspace <project> --env-file <dotenv-path>`. Add explicit `--baseline-provider`, `--baseline-model`, and `--effort` only when known.
6. Read the saved report. Distinguish verified, provisional, failed, incompatible, and unverified results. Say “no verified improvement” when appropriate. Recommendations apply only to recorded environments and evaluated cases.
7. Run a verified profile with `harness-opt run <profile.json> '<task>' --budget-usd <user-budget> --time-limit <user-seconds> --workspace <project>`.

Never overwrite the original target or global runner settings. Keep required outputs,
security, permissions, hooks, and fixed subagent models. Do not silently reduce effort
or discard unsupported API fields. Never launch production external-service cases;
those need a resettable test connection and fixture data. Do not claim cross-provider
Claude Code compatibility without a successful recorded native-runner check.
