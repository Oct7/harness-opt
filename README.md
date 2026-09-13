# harness-opt

Run skills and plugins through native Claude Code or Codex, measure quality,
completion time and cost, and retain only improvements verified on generated cases.
The original target and user settings are never intentionally overwritten.

**Development preview.** Offline checks and native plugin installation are tested;
paid end-to-end provider compatibility is a release gate, not an established claim.

## Install

Requires macOS or Linux, Python 3.11+, and `claude` or `codex` on PATH.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./plugins/harness-opt
.venv/bin/harness-opt --help
```

The plugin directory includes execution code, baseline defaults/capture rules, and
evaluation definitions. The actual baseline model/effort is resolved at run time
from native settings or explicit input. Credentials and private results are kept
outside the distributed plugin. After marketplace installation, install its
Python package from the installed plugin directory using the same command.

Claude Code local marketplace:

```sh
claude plugin marketplace add /absolute/path/to/harness-opt
claude plugin install harness-opt@harness-opt
```

Codex local marketplace:

```sh
codex plugin marketplace add /absolute/path/to/harness-opt
codex plugin add harness-opt@harness-opt
```

Public GitHub marketplace: use `Oct7/harness-opt` in place of the local path in
either command. Repository: https://github.com/Oct7/harness-opt.
Invoke the `harness-opt` skill in either tool; it uses the calling native runner
and guides provider/key setup, target or demo selection, baseline model/effort,
mode, final repetitions, budget and time limit before execution. Previously
specified choices are reused for that run; three repetitions are recommended.
See the official [Claude plugin reference](https://code.claude.com/docs/en/plugins-reference)
and [Codex plugins documentation](https://developers.openai.com/codex/plugins).

## Configure providers

The skill guides this setup when a user wants to run an evaluation. A real target
or API key is not required just to install, inspect, or develop harness-opt.

Prepare a provider entry without making API calls:

```sh
harness-opt configure openrouter --env-file /path/to/project/.env
# Import a key already held in an environment variable (the value is not an argument):
harness-opt configure openrouter --env-file /path/to/project/.env --api-key-env OPENROUTER_API_KEY
# Or enter it privately in a local interactive terminal:
harness-opt configure openrouter --env-file /path/to/project/.env --prompt-key
```

Without a key, `configure` writes a template and returns `needs_api_key`. It preserves
unrelated settings and existing keys, writes with mode 0600, and never prints keys.
`configured` only means the fields were stored; no authentication/model call was made.
Ollama has a local URL preset; custom providers use `--base-url`. Baseline model,
effort, mode, repetitions, dollar budget and seconds are chosen in the skill before
execution; dollar/time limits are never silently filled in.

Store credentials in a local `.env` (gitignored), or set environment variables.
Each provider is independent:

```dotenv
HARNESS_LOCAL_BASE_URL=http://127.0.0.1:8000/v1
HARNESS_LOCAL_API_KEY=replace-locally
HARNESS_LOCAL_MODELS='[{"id":"your-model-id","litellm_model":"openai/your-model-id","input_per_million":1.0,"output_per_million":3.0,"context_window":32768,"efforts":["low","medium","high"],"capabilities":["tools"],"price_source":"user verified contract"}]'
```

The prices and capabilities above are **illustrative**, not claims about any model.
Use your provider's actual limits and billing terms. `/models` is queried first;
`HARNESS_<NAME>_MODELS` adds model IDs or overrides metadata. Unknown endpoints never
receive an invented available-model list. Unverified IDs remain unverified until
called successfully. Unknown prices exclude automatic cost recommendations.
OpenRouter pricing is read from its [model API](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties).

```sh
harness-opt models --openrouter  # public price catalog; no API key or paid request
harness-opt models --env-file .env
harness_demo_dir=$(mktemp -d)
cp -R ./plugins/harness-opt/examples/file-skill "$harness_demo_dir/skill"
harness-opt optimize "$harness_demo_dir/skill" --runner codex --mode all \
  --workspace "$harness_demo_dir" --baseline-provider local --baseline-model your-model-id \
  --effort medium --repeats 3 --budget-usd 2 --time-limit 600
harness-opt report RUN_ID
harness-opt run /path/to/profile-1.json 'Summarize input.txt' \
  --workspace /path/to/project --budget-usd 1 --time-limit 120
```

Dollar budgets and time limits (seconds) are required, with no paid defaults.
State defaults to `~/.cache/harness-opt`, outside the experiment workspace; override
with `--state-dir`. A state directory inside the workspace is rejected to avoid
recursive snapshots. `--force` bypasses cached cases and quality failures;
`--resume RUN_ID` resumes compatible saved work. `--budget-usd` is the cumulative
ceiling including earlier invocations; `--time-limit` starts a new wall-clock window.

## Evaluation and outputs

Modes: `steps`, `speed`, `cost`, `structure`, or `all` (default). Original requirements
are frozen before proposals. Direct artifact checks precede blinded baseline-model
judgment. Finalists receive reversed-order judgment and `--repeats` executions per
case (default/recommended: 3). One or two repetitions are allowed for quick trials
and yield provisional candidates only, without verified replay profiles.
Promotion requires quality plus lower measured cost **and** shorter completion time.
A cheaper token price alone does not qualify. No improvement is a valid outcome.

Before baseline execution, each run saves `cases.json` with frozen criteria, fixtures
and the exploration/held-out split. The report links it and records whether cases
were reused. Cases remain in SQLite as well.

Every run writes Markdown and JSON reports, SQLite records, call telemetry, and—when
validated—an improved copy, unified diff, and replay profile. Unknown costs and
unverified work remain explicit. Aliased-model quality failures expire after seven
days; authentication/transport problems never become cached quality failures.

The loopback gateway preserves same-format native requests using HTTP passthrough,
and uses LiteLLM's [Messages](https://docs.litellm.ai/docs/anthropic_unified)
and [Responses](https://docs.litellm.ai/docs/response_api) adapters for protocol conversion. It reserves cost
before dispatch and stops when usage cannot be reconciled. Input/output usage,
cache tokens, provider cost versus estimates, duration, measured TTFT, and effective
TPS are recorded. TTFT stays absent if the stream provides no measurable text event.
Fixed subagent model requests must have their own priced metadata; they are never
silently rerouted as the primary model. Unsupported fields fail compatibility.

Claude Code with non-Claude providers is outside the supported combinations in
[Anthropic's gateway guidance](https://code.claude.com/docs/en/llm-gateway). Reports
must be interpreted against their actual runner/gateway/model versions.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/native_smoke.py  # optional: installed CLIs, loopback-only providers
.venv/bin/python -m pip wheel --no-deps ./plugins/harness-opt -w dist
```

CI covers Python 3.11 and 3.13 on Linux and macOS. Local validation uses Claude Code
2.1.263, Codex CLI 0.154.0 and LiteLLM 1.100.1. Both marketplaces were installed
successfully using temporary HOME/config directories, without changing user settings.
Both actual CLIs also completed text and file-tool round trips against loopback
providers (four smoke scenarios), with measured usage and streaming timing.
The default unit/integration suite contains 48 checks; it does not require paid APIs.

Before a stable release, supply a provider and explicit paid budget, verify real file
work, hooks and subagents end to end in both runners, then promote the development preview to a stable release. Baseline capture covers explicit model/effort and native files on disk; session-only
overrides are not automatically recovered. Hook/MCP optimization is currently
blocked unless external isolation can be verified (no fixture-approval CLI is shipped).
Linked worktrees and symlinked workspaces are rejected. Unsupported cross-protocol
reasoning, Anthropic beta features and hosted/media tools fail compatibility instead
of being silently dropped. A directory copy alone is not an operating-system sandbox. Do not use production
service credentials or targets as evaluation fixtures.

Reference pattern provenance is in `plugins/harness-opt/references/patterns.json`.
Patterns are original descriptions; no upstream skill implementation is vendored.
Anthropic/OpenAI references have per-file licensing; Superpowers and gstack are MIT.
The pinned OpenAI skills repository is deprecated and is retained only as historical
pattern provenance. Project code is MIT licensed.

Other execution harnesses and provider tools are surveyed in the bundled
[harness reference](plugins/harness-opt/references/harnesses.md). OpenCode, Gemini CLI,
Pi, Aider, Cline and Copilot CLI are researched candidates, not implemented runners.
opencodex/LiteLLM are transport options; Ollama supplies model inference.

The selected next adapter priorities are **OpenCode, then Pi**. Users should use
one existing harness, not install every harness. A direct API answer benchmark can
compare model responses and usage, but cannot establish native tool/hook/MCP skill
behavior; no standalone direct-API evaluation mode is implemented.

With no target, start with the bundled file-summary demo; further public candidates
and their prerequisites are listed in [the target guide](plugins/harness-opt/references/targets.md).
The [setup guide](plugins/harness-opt/references/setup.md) is bundled in the plugin too.
