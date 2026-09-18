# Setup inside the skill

Guide setup when the user starts an optimization. Reuse supplied choices; developing
or discussing harness-opt itself does not require live credentials or a target.
If `harness-opt` is missing from PATH, install first:
`uv tool install git+https://github.com/Oct7/harness-opt.git`.

## Question delivery (all setup choices)

- Reuse explicit answers already supplied in this run, including plain-text replies.
  These are configuration choices, not separate permission requests; do not add
  approval language or explanations that the skill requires confirmation.
- Use a selection-UI tool only when available and allowed in the current mode.
  Put the question and options in that tool once; do not repeat them in commentary
  or the final response. If no allowed selection tool exists, ask once in plain text.
- Keep at most one unanswered question pending. An asynchronous tool returning
  means the question was posted, not answered. Wait for the actual user reply using
  the host's supported waiting mechanism; do not reissue the question, ask the next
  one, or end with a duplicate question while it is pending. Continue only work that
  does not depend on the missing answer. A preselection, timeout, or empty result is
  not an answer and does not authorize a required limit.
- When a reply arrives, record the choice and advance to the next missing setting.
  Answer status or diagnostic requests without restarting setup. If the user changes
  an earlier choice, retain the other answers that still apply.

## Skill optimize or Class route

After the calling runner is known, ask one question: **Skill optimize** or
**Class route**. Reuse the answer. Do not mix paths. Class route failure does
not fall through to skill optimize.

For **Class route**, skip skill catalog/mode questions. Ask one at a time:

1. If routing is stale, propose `harness-opt report --runner <runner>` first.
2. `harness-opt report --runner <runner>` then `harness-opt hook install`. End hook is good/bad only.
3. Run `harness-opt catalog --scope project --runner <runner> --workspace <workspace> --view classes`. User picks a `calibratable` class.
4. Execution: current (recommended) or api. Grok is current only.
5. Repeats: 3 / 1 / 5 / custom.
6. Time limit per invocation: 300 / 600 / 1200 / custom. No implied default.
7. If api: the provider/budget questions below.
8. If isolate required: run `isolate`, pass `--native-home`.
9. Show class, runner, ceiling model/effort, execution, repeats, limits, then run `calibrate` once.

Do not offer `steps` / `structure` / `all` on this path. `--runner cursor` is an error.

For **Skill optimize**, continue below.

## Choose execution first

Offer **Current environment improvement** (recommended) and **API model comparison**.
Both execute the user's native harness in isolated local copies. Neither changes
the API connection or model of the active conversation.

| Choice | Connection | Modes | Required limits | Recommendation |
| --- | --- | --- | --- | --- |
| `current` (default) | Existing native login and model/effort | `all` = steps + structure, `steps`, `structure` | Time in seconds | Quality passes, time or reported tokens decrease, other known metric does not worsen |
| `api` | Explicit provider/model through an experiment-only gateway | `all`, `steps`, `structure`, `speed`, `cost` | USD ceiling and time in seconds | Quality passes, measured dollars and completion time both decrease |

Current execution needs no new API key. Existing account billing and quotas still
apply; dollar cost is unknown and no dollar ceiling can be enforced. Do not call it
free. Do not ask for a provider, run `configure`, or load HARNESS settings for this
choice. Native environment variables and credential files are preserved in copied
configuration. Keychain-only credentials may be inaccessible there; report an
authentication failure as unverified, without extracting credentials or changing
the user's original login. Disk configuration is captured; session-only overrides
need explicit reproduction. Keep any known current model/effort overrides fixed.

## Common choices

1. Use the calling harness. Current adapters are Claude Code, Codex, and Grok;
   OpenCode, then Pi, are planned. Grok runs `--execution current` only. Other hosts
   can inspect setup/catalogs but do not yet have a full execution adapter. Never ask
   users to install every harness.
2. Ask one selection question: **Global skills** or **Project skills**. Never offer
   harness-opt itself as a target, even when the working repository is harness-opt.
   Find the bundled runtime two directories above the skill directory and install
   into a writable virtual environment if needed. Run:

   ```sh
   harness-opt catalog --scope global --runner codex --workspace /path/to/project
   ```

   Substitute the selected scope and calling runner. Global discovery includes native
   skills and plugin caches; project discovery includes project skills and plugins.
   Paths distinguish same-name skills; caches may contain inactive versions.
3. If the catalog has observed usage, ask one question with **Frequently used**,
   **Recently used**, **All skills**. Rerun with `--view frequent|recent|all`.
   Otherwise explain that usage is unknown and show all skills immediately.
   Render the returned list with name, plugin, path, observed session count and last
   observed invocation. Paginate if necessary, keeping the entire list accessible.
   Ask the user to select a listed skill; do not require them to remember a path.
   If they request a list, show it before asking more configuration questions.
   Only when no skills exist, offer the bundled demo in a fresh workspace.
   Stage global targets in a fresh workspace with required relative references and
   permissions preserved. Never use installed plugin caches as experiment workspaces.
4. Ask these settings **one at a time**, waiting after each answer. Reuse supplied
   choices; do not batch questions or ask for comma-separated text:
   - Mode: current `all` (recommended), `steps`, `structure`. Grok current also accepts `speed`/`cost` using `grok models` at the captured effort; dollars stay unknown. API additionally `speed`, `cost` with metered USD.
   - Final repetitions per candidate per case: **3 (recommended)**, **1 (provisional)**,
     **5**, or a custom positive integer. Judge calls are additional; below 3 yields
     no verified replay profile.
   - Time limit **per native invocation**: **300 seconds**, **600 seconds**,
     **1200 seconds**, or custom positive seconds. It does not cap the whole optimize
     run. There is no default authorization; wait for an explicit selection.
5. For API comparison, complete the additional provider steps below. For current
   execution, proceed directly with `--execution current` and no `--budget-usd`.
6. Show target, runner, execution choice, model/effort, mode, repetitions and limits,
   then execute once supplied. If live hooks/MCP are present (typical for Codex) or
   `optimize` reports they require an isolated fixture, create an approved native
   HOME first. Do not copy the live config tree and do not ask the user to invent a
   sandbox:

   ```sh
   harness-opt isolate --runner codex
   ```

   Substitute the calling runner. Default destination is
   `~/.cache/harness-opt/native-home/<runner>`. The command copies model/effort and
   native login files only; live hooks, MCP servers, plugins and notify commands are
   omitted. A clean existing fixture is reused; `--force` replaces a dirty one.
   Never use the live user home, `~/.codex`, `~/.claude`, `~/.grok`, or the installed plugin
   directory as the destination. Pass `native_home` from the result as
   `--native-home` on `optimize`. Project-workspace hooks/MCP still block evaluation.
   Link the frozen `cases.json` and report.

## API comparison only

Ask which provider to use, offering existing configuration first. OpenRouter has a
bundled URL preset and public prices. Ollama supplies a local endpoint; its preset
does not verify a model or account for hardware costs. Custom providers, including
existing LiteLLM/opencodex servers, need a base URL.

Prepare `.env` outside the installed plugin. These commands make no API calls,
preserve unrelated settings and write with owner-only permissions:

```sh
harness-opt configure openrouter --env-file /path/to/project/.env
harness-opt configure custom --base-url https://provider.example/v1 --env-file /path/to/project/.env
```

Without a key this creates a template and reports `needs_api_key`. Never ask for
secrets in chat. Reference an existing environment variable by NAME, without
expanding its value:

```sh
harness-opt configure openrouter --env-file /path/to/project/.env --api-key-env OPENROUTER_API_KEY
```

Otherwise the user can edit the file locally or enter a key privately in their
interactive terminal (noninteractive input is refused):

```sh
harness-opt configure openrouter --env-file /path/to/project/.env --prompt-key
```

Never print the file. `configured` means stored, not authenticated or verified.
Process environment values take precedence; configure reports a key override.

Read relevant model IDs with `harness-opt models --env-file /path/to/project/.env`.
`models --openrouter` reads public prices without a key and does not prove key validity.
Resolve the baseline model/effort from native settings or explicit user choices.
Do not invent availability, supported effort, context limits or missing prices.

Ask for an explicit USD ceiling in addition to the common mode/repetition/time
choices. It covers experiment generation, baselines, candidates and judges; the
parent conversation's usage is separate. A previous run's allowance is not new
spending permission. On `--resume`, the USD ceiling includes prior experiment spend;
the time limit starts a new invocation window. Pass `--execution api` explicitly.

API comparison still uses a native harness. A standalone API answer benchmark would
not verify native tools, hooks, MCP or subagents; no such evaluation mode is shipped.

## Usage-based maintenance suggestions

`catalog` reads local Codex session JSONL or Claude project JSONL without network
calls or printing conversation content. `--days 90` is the default observation
window. It counts sessions with explicit user invocations or Claude Skill tool
calls, not implicit use or successful completion. Project usage requires an exact
matching recorded workspace. Malformed records and ambiguous names are reported;
missing history is unknown, never evidence of disuse.

When asked what to improve or remove, show `suggestions` with count, last use,
coverage and rationale. Frequent/recent use helps prioritize improvement; absence
of observations only nominates a removal review. For plugin removal reviews, check
whether it is installed/enabled and whether its hooks, MCP, commands or dependencies
are needed. Cached versions alone are not installed-plugin evidence. Do not delete,
uninstall, or alter settings as part of cataloging or suggesting.

Normal directory aliases such as `latest` are supported during native capture and
copying. Actual ancestor cycles remain rejected with their path; do not silently
skip configuration, change the user's links, or claim evaluation succeeded.
