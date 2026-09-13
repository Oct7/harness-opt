---
name: harness-opt
description: Improve a skill or plugin using the current coding harness and login, or set up separate API model comparisons with measured budgets.
---
Use the bundled Python CLI. Do not substitute your own agent loop or simulate measurements.

1. Follow `../../references/setup.md`. First offer **Current environment improvement** (recommended, `--execution current`) or **API model comparison** (`--execution api`). Reuse supplied choices. Setup belongs in this skill; developing or discussing harness-opt itself needs no live target or credentials.
2. Use the calling harness: Claude Code or Codex. OpenCode then Pi are planned. Other hosts can use setup/catalog inspection but need their own adapter for full optimization. Never silently switch harnesses or require installing them all. See `../../references/harnesses.md`.
3. Current environment improvement uses existing native authentication and model/effort settings in separate local runs. Do not request an API key, configure a provider, or load HARNESS provider settings. Existing account billing and quotas still apply; no dollar ceiling is enforced. The active conversation's API connection is unchanged. Session-only model/effort overrides must be supplied explicitly if known.
4. API model comparison uses separate native evaluation processes and a temporary gateway. Only for this choice, guide provider/key setup, baseline model/effort and an explicit dollar ceiling using the setup reference. Never imply that a skill can switch the active conversation's provider. `configure` stores settings without API calls; `models --openrouter` reads the public price catalog. Neither proves authentication or compatibility.
5. Before execution, ask for missing mode, final repetitions and time limit using the host's selection UI:
   - Current modes: `all` (recommended: steps + structure), `steps` (process/instructions), `structure` (references/scripts).
   - API modes: `all` (recommended: all four modes), `steps`, `structure`, `speed` or `cost` (model/effort comparisons).
   - Final executions per candidate per case: 3 (recommended), 1 (quick, provisional), 5, or another positive integer. Exploration runs once per case; judge calls are additional. Below 3 produces no verified replay profile.
   - Wall-clock seconds are required for both paths; dollar budget is required only for API experiments. Never invent either limit. Wait for the user's choices for this run.
6. Locate the plugin root at `../..` relative to this skill directory. Install its package in a writable virtual environment if needed. Offer bundled `examples/file-skill` in a fresh workspace when no target exists, or see `../../references/targets.md`. Show the target, runner, execution choice, model/effort, mode, repetitions and limits, then execute:

   ```sh
   harness-opt optimize <target> --runner <runner> --execution current --mode <mode> --repeats <count> --time-limit <seconds> --workspace <workspace>
   harness-opt optimize <target> --runner <runner> --execution api --mode <mode> --repeats <count> --time-limit <seconds> --budget-usd <budget> --workspace <workspace> --env-file <dotenv-path> --baseline-provider <provider> --baseline-model <model> --effort <effort>
   ```

   Use the one selected command. No extra permission question is needed once the choices are supplied. Authentication failures remain unverified; isolated native login can be unavailable with keychain-only credentials. Report the runner's guidance without demanding a new API key or modifying global authentication.
7. Show `cases.json` and the report path. Cases, fixtures, frozen criteria and the held-out split are saved before baseline execution. Never give held-out cases to proposal generation. Current recommendations compare quality, completion time and reported tokens; unknown dollars stay unknown. API recommendations require lower measured cost and shorter time. Distinguish reused, provisional, failed and verified results.
8. Run a verified profile with `harness-opt run <profile.json> '<task>' --time-limit <seconds> --workspace <workspace>`. Add `--budget-usd <budget> --env-file <dotenv-path>` only for an API profile. The profile records its execution path. Recommendations apply only to recorded environments and evaluated cases.

Keep execution code, baseline defaults/capture rules, evaluation definitions and
static references inside the plugin. Actual credentials belong in the user's local
configuration; private run data defaults to `~/.cache/harness-opt` or `--state-dir`
outside the target workspace. Preserve original files, native permissions, required
outputs, hooks and fixed subagent models. Unsupported API fields and external-service
cases that cannot be reset stay unverified. A direct API answer test does not verify
the user's native skill execution; no standalone API evaluation mode is implemented.
