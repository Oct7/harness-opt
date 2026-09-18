# Harness Opt plugin

This directory is a self-contained Claude Code/Codex plugin and Python package.
Grok is an additional current-environment runner (`--runner grok`); it has no
metered API-gateway adapter yet.
It includes the execution code (`harness_opt/runner.py` and `gateway.py`), baseline
defaults and capture rules (`cli.py` and `runner.py`), and evaluation definitions
(`evaluation.py` and `optimizer.py`). Static reference patterns are bundled too.
The actual baseline model/effort is resolved from native settings or explicit input
when a run starts; credentials and private run results are not distribution assets.
Install the CLI on PATH (`uv tool install git+https://github.com/Oct7/harness-opt.git`
or `pip install .` from the repo root), then:

```sh
harness-opt hook install
harness-opt models --openrouter
```

The skill first asks **Skill optimize** or **Class route**. Skill optimize
offers current environment improvement (recommended) or API model comparison,
then global or project skills. Class route writes an observational report,
installs start/end hooks (`good`/`bad` only at session end), then can run
`calibrate` for a listed class. Routing stays in
`~/.cache/harness-opt/model-routing/routing.json`.

```sh
harness-opt report --runner codex
harness-opt route '로그인 오류 원인' --host cursor --model grok-4.6 --effort xhigh
harness-opt feedback --class debug_investigate --host cursor --model grok-4.6 --effort high --verdict good
harness-opt hook install
```

`hook install` writes Cursor `~/.cursor/hooks.json`. Claude Code uses this plugin's
`hooks/hooks.json` (`UserPromptSubmit` / `Stop`). End verdict is `good` / `bad` only.

List skills, usage suggestions, or task classes locally:

```sh
harness-opt catalog --scope global --runner codex --view frequent
harness-opt catalog --scope project --runner claude --workspace /path/to/project --view all
harness-opt catalog --scope project --runner codex --workspace /path/to/project --view classes
```

Counts mean sessions with explicit invocation signals in the last 90 days
(`--days` changes the window). Missing history is unknown, not unused. Cached
plugins may be inactive; removal suggestions require checking other capabilities.
The command never deletes files or calls a model.

Live hooks/MCP block `optimize` and `calibrate` until an approved fake HOME exists:

```sh
harness-opt isolate --runner codex
harness-opt optimize /path/to/skill --runner codex --time-limit 600 --native-home ~/.cache/harness-opt/native-home/codex
harness-opt calibrate --class debug_investigate --runner codex --time-limit 600 --native-home ~/.cache/harness-opt/native-home/codex
```

`isolate` copies model/effort and native login files only. `--force` replaces a dirty destination.

Current execution uses existing native login/model settings, needs no new API key,
and compares quality, time and reported tokens. Existing account billing/quotas
apply; dollars are unknown and no USD ceiling is enforced. Keychain-only native
login may be unavailable in copied configuration and remains unverified.

Provider/key setup is included only when API comparison is selected. Use
`harness-opt configure openrouter --env-file /path/to/project/.env` to prepare a
configuration without calling an API; use `--api-key-env NAME` or local terminal
`--prompt-key` for private credential entry.

The public OpenRouter catalog requires no API key. `--execution api` requires
`HARNESS_<NAME>_BASE_URL` and `HARNESS_<NAME>_API_KEY` in `.env` or the environment,
and explicit `--budget-usd` / `--time-limit` values. `--time-limit` is per native
invocation. The default `--execution current` requires only that per-call limit.
Neither path changes the active conversation's
connection. Use `--help` for each command.

The shared skill is `skills/harness-opt/SKILL.md`. Full setup, pricing metadata,
verification and preview limitations: https://github.com/Oct7/harness-opt#readme.

This is a development preview. Recommendations only cover recorded environments
and generated cases. Live hooks/MCP require `harness-opt isolate` and
`--native-home` before `optimize`; paid provider integration remains a release
gate. Project code is MIT licensed. Reference descriptions are original summaries
with pinned source provenance in `references/patterns.json`.

No target yet? Copy `examples/file-skill` into a fresh workspace, or consult
`references/targets.md`. Full guided setup is in `references/setup.md`.
