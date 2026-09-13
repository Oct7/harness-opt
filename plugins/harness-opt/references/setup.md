# Setup inside the skill

Guide setup when the user starts an optimization. Reuse supplied choices; developing
or discussing harness-opt itself does not require live credentials or a target.

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

1. Use the calling harness. Current adapters are Claude Code and Codex; OpenCode,
   then Pi, are planned. Other hosts can inspect setup/catalogs but do not yet have
   a full execution adapter. Never ask users to install every harness.
2. Ask for a target or offer bundled `examples/file-skill`. Copy the demo into a
   fresh workspace first; never use the installed plugin as the experiment workspace.
   See `targets.md` for public candidates. Setup alone needs no target.
3. Find the bundled runtime two directories above the skill directory and install
   into a writable virtual environment if needed. No repository checkout is required.
4. Ask together for a supported mode, final repetitions (3 recommended), and time
   limit in seconds. Repetitions are per candidate per case, with judge calls in
   addition. One or two repetitions are provisional and generate no verified profile.
   Time has no default; ask only for choices missing for this run.
5. For API comparison, complete the additional provider steps below. For current
   execution, proceed directly with `--execution current` and no `--budget-usd`.
6. Show target, runner, execution choice, model/effort, mode, repetitions and limits,
   then execute once supplied. Link the frozen `cases.json` and report. If hooks/MCP
   prevent reproducibility, request only fixture information needed by that target.

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
