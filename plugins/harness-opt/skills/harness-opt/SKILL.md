---
name: harness-opt
description: Set up providers and evaluation settings, then measure and optimize a skill or plugin in the user's native coding harness for quality, cost and completion time.
---
Use the bundled Python CLI. Do not substitute your own agent loop or simulate measurements.

1. When the user wants to evaluate a skill, follow `../../references/setup.md` to guide them through target/demo selection, provider configuration, key setup, baseline model/effort, budget and time limit. Setup is part of this skill; the user does not need to arrive with those decisions already made. Reuse supplied values and ask only for what is missing. If they are developing or discussing harness-opt itself, do not require a live target or API credentials.
2. Use the user's current harness. Native adapters currently support Claude Code and Codex; OpenCode then Pi are planned. Never silently switch harnesses or require installing every supported harness. Other hosts can use setup and model discovery now, but full optimization requires their native adapter. Consult `../../references/harnesses.md` for the distinction between harnesses, proxies and model servers.
3. Before execution, ask for the mode and final repetitions together with any missing limits, using the host's selection UI when available. Wait for choices already authorized for this run:
   - Mode: `all` (recommended), `steps` (process/instructions), `structure` (references/scripts), `speed` (model/effort), or `cost` (model/effort).
   - Final executions per candidate per case: 3 (recommended), 1 (quick, provisional), 5, or another positive integer. Exploration runs once per case. Counts below 3 produce no verified replay profile.
   - Dollar budget and wall-clock seconds must be supplied by the user. Never invent spending limits.
4. Locate the plugin root at `../..` relative to this skill directory. Install the bundled package in a writable virtual environment when needed. `harness-opt configure` prepares provider settings without API calls; `models --openrouter` reads the public price catalog. A listing or stored key is not verified model compatibility.
5. If no target is available, offer the bundled `examples/file-skill` in a fresh workspace or candidates in `../../references/targets.md`. Show the selected target, runner, provider/model/effort, mode, repetitions and limits. Then run `harness-opt optimize <target> --runner <runner> --mode <mode> --repeats <count> --budget-usd <budget> --time-limit <seconds> --workspace <workspace> --env-file <dotenv-path>` with known baseline overrides. No extra permission question is needed after those choices are supplied.
6. Show `<state-dir>/<run-id>/cases.json` and the report path. Cases include frozen criteria, fixtures and the exploration/held-out split and are saved before baseline execution. Never provide held-out cases to proposal generation. Distinguish reused cases, provisional results, failures and verified recommendations.
7. Run a verified profile with `harness-opt run <profile.json> '<task>' --budget-usd <budget> --time-limit <seconds> --workspace <workspace>`. Recommendations apply only to recorded environments and evaluated cases.

Keep execution code, baseline defaults/capture rules, evaluation definitions and
static references inside the plugin. Actual credentials belong in the user's local
configuration; private run data defaults to `~/.cache/harness-opt` or `--state-dir`
outside the target workspace. Preserve original files, native permissions, required
outputs, hooks and fixed subagent models. Unsupported API fields and external-service
cases that cannot be reset stay unverified. A direct API answer test does not verify
the user's native skill execution; no standalone API evaluation mode is implemented.
