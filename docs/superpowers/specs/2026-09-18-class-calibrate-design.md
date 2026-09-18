# Class calibrate

Date: 2026-09-18  
Status: draft pending review  
Scope: one new command and catalog view. Skill optimize (`optimize`) is unchanged.

## Problem

harness-opt only measures `SKILL.md` targets. The user’s daily agent work is classified by task type (debug, UI tweak, implement, …). Model and effort are chosen by habit, usually at the session ceiling. We need the same frozen-case, isolated, judged loop for those types, writing only `{model, effort}` into a routing table.

## Non-goals

- Hooks that ask to switch models (`beforeSubmitPrompt`). Propose that when the model catalog or this file’s cutoff changes.
- Cursor runner or Cursor-verified profiles.
- Rewriting AGENTS.md, skills, hooks, or process text (`steps` / `structure`).
- Generating cases with a model.
- Multi-repo case packs in one run.
- Changing the active conversation’s provider or model.
- Inventing native model IDs that the runner did not list.

## Locked decisions

| Item | Choice |
| --- | --- |
| Product | Session optimizer: replay cases, compare, save profile |
| Unit | Task class |
| Profile contents | `model` + `effort` only |
| Case source | Historical user prompts in `(runner, workspace, class)` |
| Workspace | Current snapshot of the chosen repo, not a historical commit |
| Command | `calibrate` (does not call `optimize`) |
| Shared code | `runner`, `WorkspaceSnapshot`, `isolate`, `Budget`, judge, `Store` |
| Modes | Implicit speed/cost. No `steps` / `structure` / `all` |
| Runners | `claude`, `codex`, `grok`. `cursor` is an error |
| Routing file | `{state-dir}/model-routing/routing.json` |
| Hook | Out of this spec |

## Classes

Deterministic local classifier. No model call. Same function for catalog counts and calibrate case pick.

| `class` | Calibrate? |
| --- | --- |
| `debug_investigate` | yes |
| `implement_feature` | yes |
| `ui_tweak` | yes |
| `ui_redesign` | yes |
| `architecture_greenfield` | yes |
| `review_audit` | yes |
| `research_docs` | yes |
| `harness_plugin` | yes |
| `content_oneshot` | yes |
| `git_deploy_ops` | no — excluded as mutating; picking it is an error |
| `multi_system_incident` | yes — nightly/canary/CI red plus two or more failing jobs or systems in one prompt |
| `mixed_or_unclear` | no — never offered, never calibrated |

Keyword rules live in one module (for example `harness_opt/classify.py`). `multi_system_incident` wins over `debug_investigate` when both match. Session noise is dropped before classify: `AGENTS.md` dumps, `<environment_context>`, `<skill>` payloads, developer/system wrappers. Prompt text after those filters is classified. `cwd` must resolve to the workspace.

## Catalog

```
harness-opt catalog --scope project --runner <r> --workspace <w> --view classes
```

`--view` gains `classes`. Other views stay skill-only.

When `view=classes`:

- `skills` is `[]`.
- `classes` is a list of `{name, count, last_seen, calibratable}`.
- `count` is distinct sessions with at least one real user prompt of that class in this workspace (same 90-day window as `--days`).
- `calibratable` is true only if, after exclusions below, at least two `normal`, one `boundary`, and one `failure` can be assigned.
- `git_deploy_ops` and `mixed_or_unclear` appear for visibility with `calibratable: false` when count > 0.

Global scope + `classes` is an error: classes are workspace-local.

## Cases

`calibrate` does not call the case-generation model. It builds `cases.json` from history.

Exclusions (do not enter the set):

- class `git_deploy_ops`
- prompts that only ask to commit, push, deploy, or mutate an external service
- cases that would set `external_services` without a user-supplied reset command (same `unverified_reason` rule as today)

Kind assignment, in order, using only that session:

1. `failure` — a later real user turn in the same session is a retry, error report, or “고치/안 됨/실패”, or the native log records a failed tool/run for that turn.
2. `boundary` — remaining prompts shorter than 80 characters, or a single sentence without a file/path/error token.
3. `normal` — the rest.

Need exactly four cases for the run: two `normal`, one `boundary`, one `failure`. Selection: most recent that fill those slots. The last of the four is `heldout`; the other three are exploration. If any slot is empty, exit nonzero and write nothing.

Each case:

- `id`, `kind`, `split` — same as `validate_cases`
- `prompt` — the historical user text
- `criteria` — every explicit success sentence in the prompt; if none, one string: `Satisfy the user request as written.` plus the prompt. No LLM rewrite.
- `files` — empty unless the session already attached file text (then copy those strings only)
- `required_files` / `file_contains` — empty. Do not invent paths.

`validate_cases` still runs. Do not add a second validator.

Replay uses the **current** workspace snapshot. Historical prompts on today’s tree can fail fairly; that is a miss, not a license to edit the tree before the run.

## Command

```
harness-opt calibrate --class <class> --runner <claude|codex|grok> --workspace <w>
  --execution current|api --repeats <n> --time-limit <seconds>
  [--budget-usd <usd>] [--env-file] [--baseline-provider] [--baseline-model] [--effort]
  [--native-home] [--state-dir] [--force] [--resume]
```

Required: `--class`, `--runner`, `--time-limit`, `--workspace` (defaults to cwd).  
`--execution` default `current`.  
`--repeats` default 3.  
`--cases` is not a flag; the count is always 4 from history.

`--mode` is rejected. `--class git_deploy_ops` and `--class mixed_or_unclear` are rejected. `--runner cursor` is rejected.

Identity fingerprint: `{execution, workspace snapshot, class, ceiling profile, case prompts, baseline}`. Resume must match. State dir must stay outside the workspace.

`run` of a calibrate profile is the existing `harness-opt run <profile> '<task>'` with empty skill changes.

## Execution

1. `capture_profile` at the native model/effort. That pair is the **ceiling**. Session-only overrides must be passed as `--baseline-model` / `--effort` if they differ from disk.
2. Live hooks/MCP without `--native-home` from `isolate` → same error as `optimize`.
3. Snapshot workspace. Each trial restores a fresh copy. No writes to the user’s tree.
4. Baseline: captured model + effort, each exploration case once.
5. Candidates: model×effort pairs **at or below** the ceiling (see below). Skip the baseline pair. Skip any pair that invents a model ID.
6. Explore on the three non-held-out cases. Confirm passing candidates on all four cases, `repeats` times. `repeats < 3` → `provisional_improvement`, no routing write.
7. Judge: existing bidirectional `judge_prompt` + `direct_checks` (usually empty). Indeterminate or below → not a win.
8. Win (same as `optimize`):
   - `current`: judge pass and (mean duration < baseline or mean tokens < baseline); do not require USD.
   - `api`: judge pass and lower USD and lower duration.
9. Quality drop never wins on price or speed alone.
10. Do not change the host conversation’s model.

Budget and time semantics copy `optimize`. `BudgetExceeded` / timeout → `budget_stopped`, no routing write.

### Candidates vs ceiling

Effort order is the list the runner actually exposed, not a hardcoded global ladder.

- **Grok + `current`:** use `native_models()` as it exists (other listed model IDs at the captured effort when that effort is allowed). Do not add a lower-effort ladder on the same Grok model in this spec. Drop any pair above the ceiling. If the captured effort is missing from a model’s allowed list, that model is not a candidate.
- **Claude / Codex + `current`:** `native_models()` is empty. Do not invent Codex/Claude model IDs. Candidates are **effort-only** on the captured model, and only efforts that native config or an explicit `--effort` probe already listed for that model. If the only listed effort is the ceiling, exit nonzero: `no candidate below ceiling; use --execution api`.
- **`api`:** discovered provider models. Drop a model with unknown prices when comparing cost. Drop any pair whose listed effort ranks above the captured ceiling when the provider publishes efforts; if it publishes none, only the explicit `--effort` (≤ ceiling if both are in a shared listed set) may run.

`rank` is the index in the runner/provider-listed effort array (lower index = lower effort). Unlisted effort → not a candidate.

## Routing file

Path: `{state-dir}/model-routing/routing.json`  
Default `state-dir`: `~/.cache/harness-opt`  
Create the directory with mode `0700`. Write atomically (temp + replace). Owner-only file mode.

Schema:

```json
{
  "schema_version": 1,
  "catalog_cutoff": "2026-09-18",
  "classes": {
    "debug_investigate": {
      "recommended": {"runner": "codex", "model": "gpt-5.6-sol", "effort": "high"},
      "ceiling": {"runner": "codex", "model": "gpt-5.6-sol", "effort": "ultra"},
      "workspace_overrides": {
        "/abs/workspace": {"runner": "codex", "model": "gpt-5.6-sol", "effort": "high"}
      },
      "evidence": [
        {
          "run_id": "...",
          "runner": "codex",
          "workspace": "/abs/workspace",
          "baseline": {"model": "...", "effort": "..."},
          "winner": {"model": "...", "effort": "..."},
          "improvements": ["completion_time"],
          "repeats": 3,
          "unverified_for": ["cursor"]
        }
      ]
    }
  }
}
```

Write only on `verified_improvement`.

- `workspace_overrides[workspace]` ← winner for that run.
- `recommended` ← that winner if unset, or if the new winner beats the previous recommended on the same metrics (and is still ≤ its own run’s ceiling).
- Tie → no change.
- `unverified_for` always includes `cursor`. Add any runner that did not execute the run.

Read order for a future hook (not implemented here): override for this workspace, else `recommended`.

`calibrate` never deletes other classes. `--force` re-runs measurement; it does not wipe the file.

## Skill and setup copy

After the calling runner is known, ask one question:

**Skill optimize** or **Class calibrate**

Skill path is the current `optimize` flow, word for word.

Calibrate path, one question at a time, reuse answers:

1. Show `catalog --view classes` for this workspace. User picks a `calibratable` class.
2. Execution: current (recommended) or api.
3. Repeats: 3 / 1 / 5 / custom.
4. Time limit per invocation: 300 / 600 / 1200 / custom. No implied default.
5. If api: existing provider/budget questions from `references/setup.md`.
6. If isolate required: run `isolate`, pass `--native-home`.
7. Show class, runner, ceiling model/effort, execution, repeats, limits, then run once.

Do not offer `steps` / `structure` / `all`. Do not fall through to skill optimize on calibrate failure.

## Errors

Exit code 1, stderr `harness-opt: ...`, no routing write:

- fewer than four assignable cases after exclusions
- selected class not calibratable
- live hooks/MCP and no `--native-home`
- `--runner cursor`
- Claude/Codex `current` and no effort candidate below ceiling
- unknown class name
- state dir inside workspace
- identity mismatch on `--resume`

Judge indeterminate, quality drop, `repeats < 3`, budget/time stop: report status as today (`provisional_improvement` / `budget_stopped`), no routing write.

## Tests

Fixture: fake native home, four dated session prompts in one workspace (2 normal, 1 boundary, 1 failure), plus one deploy prompt that must be dropped.

- `catalog --view classes` counts and `calibratable` match the fixture
- `calibrate` with three prompts exits nonzero
- hooks required and no `--native-home` exits nonzero
- `--runner cursor` exits nonzero
- `--class git_deploy_ops` exits nonzero
- verified winner writes override + recommended
- provisional and `budget_stopped` leave `routing.json` bytes unchanged
- candidate above ceiling is absent from trials
- existing `optimize` tests pass without modification of their assertions

## Files to touch (implementation, later)

- `harness_opt/classify.py` — new, classifier + case pick
- `harness_opt/catalog.py` — `view=classes`
- `harness_opt/calibrate.py` — new, or a function next to `optimize` that does not call it
- `harness_opt/cli.py` — `calibrate` subcommand; `catalog --view classes`
- `skills/harness-opt/SKILL.md`, `references/setup.md` — second fork only
- `tests/test_catalog.py`, `tests/test_calibrate.py`
- plugin.json / README only if the public command list is documented there

Do not add a hook script in this spec.
