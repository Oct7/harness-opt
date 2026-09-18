---
name: harness-opt
description: List skills or workspace task classes, write a class-route model/effort report, ask via hooks, or optimize a chosen skill.
---
Use the bundled Python CLI. Do not substitute your own agent loop or simulate measurements.
If `harness-opt` is not on PATH: `uv tool install git+https://github.com/Oct7/harness-opt.git` (or `pipx install git+https://github.com/Oct7/harness-opt.git`).

After the calling runner is known (Claude Code, Codex, or Grok), ask one question: **Skill optimize** or **Class route**. Reuse the answer. Do not mix the two paths. Class route failure does not fall through to skill optimize.

**Class route** (no `steps` / `structure` / `all`; never call `optimize`):

1. If `{state-dir}/model-routing/routing.json` is stale (catalog fingerprint changed or cutoff older than 30 days), propose `harness-opt report --runner <runner>` first.
2. Run `harness-opt report --runner <runner>` to classify sessions, list every model the host agent exposes, and write `observed` at or below the current ceiling.
3. Run `harness-opt hook install`. Start hook asks to drop model/effort. End hook asks `good` / `bad` only.
4. Run `harness-opt catalog --scope project --runner <runner> --workspace <workspace> --view classes`. Show `{name, count, last_seen, calibratable}`. User picks a `calibratable` class. `git_deploy_ops` and `mixed_or_unclear` are not selectable.
5. Execution: **current** (recommended) or **api**. Grok is current only.
6. Repeats: 3 (recommended) / 1 / 5 / custom positive integer.
7. Time limit per invocation: 300 / 600 / 1200 / custom. No implied default.
8. If api: existing provider/budget questions from `../../references/setup.md`.
9. If isolate required: `harness-opt isolate --runner <runner>`, then pass `--native-home`.
10. Show class, runner, ceiling model/effort, execution, repeats, limits, then run once:

   ```sh
   harness-opt calibrate --class <class> --runner <runner> --execution current --repeats <count> --time-limit <seconds> --workspace <workspace> --native-home <destination>
   harness-opt calibrate --class <class> --runner <runner> --execution api --repeats <count> --time-limit <seconds> --budget-usd <budget> --workspace <workspace> --env-file <dotenv-path> --baseline-provider <provider> --baseline-model <model> --effort <effort> --native-home <destination>
   ```

   Replay a verified profile with existing `harness-opt run <profile> '<task>'`. Routing is `{state-dir}/model-routing/routing.json`. `--runner cursor` is an error.

**Skill optimize** — current `optimize` flow, word for word:

1. Follow `../../references/setup.md`. First offer **Current environment improvement** (recommended, `--execution current`) or **API model comparison** (`--execution api`). Reuse supplied choices. Setup belongs in this skill; developing or discussing harness-opt itself needs no live target or credentials.
2. Use the calling harness: Claude Code, Codex, or Grok. OpenCode then Pi are planned. Other hosts can use setup/catalog inspection but need their own adapter for full optimization. Never silently switch harnesses or require installing them all. Grok supports `--execution current` only; metered API comparison still needs Claude Code or Codex. See `../../references/harnesses.md`.
3. Current environment improvement uses existing native authentication and model/effort settings in separate local runs. Do not request an API key, configure a provider, or load HARNESS provider settings. Existing account billing and quotas still apply; no dollar ceiling is enforced. The active conversation's API connection is unchanged. Session-only model/effort overrides must be supplied explicitly if known.
4. API model comparison uses separate native evaluation processes and a temporary gateway. Only for this choice, guide provider/key setup, baseline model/effort and an explicit dollar ceiling using the setup reference. Never imply that a skill can switch the active conversation's provider. `configure` stores settings without API calls; `models --openrouter` reads the public price catalog. Neither proves authentication or compatibility.
5. Select the target using `../../references/setup.md`: ask **Global skills** or **Project skills**, then run `harness-opt catalog --scope <global|project> --runner <runner> --workspace <project>`. Offer **Frequently used**, **Recently used**, or **All skills** when observations exist; otherwise show the full list and explain usage is unknown. Show names and paths (including plugin ownership), then let the user select a listed skill. Never offer harness-opt itself as a target. Show usage-based improvement/removal review suggestions when requested; never delete automatically.
   Follow the question delivery rules in `../../references/setup.md` for every setup choice, including execution and scope. Ask each missing setting once, wait for its answer, then ask the next. Never bundle questions or request a comma-separated response. Reuse earlier answers:

   - Current modes: `all` (recommended: steps + structure; Grok also compares native models at the captured effort), `steps`, `structure`. Grok `speed`/`cost` compare listed `grok models` IDs without a dollar ceiling.
   - API modes: `all` (recommended: all four modes), `steps`, `structure`, `speed` or `cost` (metered model/effort comparisons). Claude/Codex model catalogs still need `--execution api`.
   - Final executions per candidate per case: 3 (recommended), 1 (quick, provisional), 5, or another positive integer. Exploration runs once per case; judge calls are additional. Below 3 produces no verified replay profile.
   - Time choices: 300 seconds, 600 seconds, 1200 seconds, or a custom positive value **per native invocation**. It does not cap the whole optimize run. No preselected value counts as consent. Wall-clock seconds are required for both paths; dollar budget is required only for API experiments. Never invent either limit. Wait for the user's choices for this run.
6. Locate the plugin root at `../..` relative to this skill directory. Install its package in a writable virtual environment if needed. Only if the selected scope has no skills, offer bundled `examples/file-skill` in a fresh workspace, or see `../../references/targets.md`. Stage global targets in a fresh workspace, retaining required relative references and permissions; never optimize inside an installed plugin cache. Show the target, runner, execution choice, model/effort, mode, repetitions and limits. If live hooks/MCP are present or `optimize` reports they require an isolated fixture, run `isolate` first and pass `--native-home` from its result (see `../../references/setup.md`). Then execute:

   ```sh
   harness-opt isolate --runner <runner>
   harness-opt optimize <target> --runner <runner> --execution current --mode <mode> --repeats <count> --time-limit <seconds> --workspace <workspace> --native-home <destination>
   harness-opt optimize <target> --runner <runner> --execution api --mode <mode> --repeats <count> --time-limit <seconds> --budget-usd <budget> --workspace <workspace> --env-file <dotenv-path> --baseline-provider <provider> --baseline-model <model> --effort <effort> --native-home <destination>
   ```

   Use the selected optimize command. Omit `--native-home` only when live hooks/MCP are absent. No extra permission question is needed once the choices are supplied. Authentication failures remain unverified; isolated native login can be unavailable with keychain-only credentials. Report the runner's guidance without demanding a new API key or modifying global authentication.
7. Show `cases.json` and the report path. Cases, fixtures, frozen criteria and the held-out split are saved before baseline execution. Never give held-out cases to proposal generation. Current recommendations compare quality, completion time and reported tokens; unknown dollars stay unknown. API recommendations require lower measured cost and shorter time. Distinguish reused, provisional, failed and verified results.
8. Run a verified profile with `harness-opt run <profile.json> '<task>' --time-limit <seconds> --workspace <workspace>`. Add `--budget-usd <budget> --env-file <dotenv-path>` only for an API profile. The profile records its execution path. Recommendations apply only to recorded environments and evaluated cases.

Keep execution code, baseline defaults/capture rules, evaluation definitions and
static references inside the plugin. Actual credentials belong in the user's local
configuration; private run data defaults to `~/.cache/harness-opt` or `--state-dir`
outside the target workspace. Preserve original files, native permissions, required
outputs, hooks and fixed subagent models. Unsupported API fields and external-service
cases that cannot be reset stay unverified. A direct API answer test does not verify
the user's native skill execution; no standalone API evaluation mode is implemented.
