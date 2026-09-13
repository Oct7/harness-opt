# Harness and model-connection survey

Checked 2026-09-13 against the primary sources below. These are integration candidates,
not newly supported harness-opt runners. Only `claude` and `codex` are implemented.

| Layer | Tool | Evidence and integration implication |
| --- | --- | --- |
| Execution harness | [OpenCode](https://opencode.ai/docs/cli/) | Noninteractive `opencode run`, JSON events, model/variant selection; [native SKILL.md discovery](https://opencode.ai/docs/skills/). Local CLI 1.18.23 help confirmed; current v2 docs must not be assumed to match v1 configuration. Requires native configuration capture and metered tool-call validation before an adapter is enabled. |
| Execution harness | [Gemini CLI](https://geminicli.com/docs/cli/headless/) | Prompt mode and JSON/JSONL responses expose usage and tool events. Requires native configuration capture and Gemini protocol metering. |
| Execution harness | [Pi](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent) | Print, JSON and RPC modes with skills and provider/model configuration; needs its own session/configuration adapter. |
| Execution harness | [Aider](https://aider.chat/docs/scripting.html) | `--message` executes an editing task and exits. Native Agent Skills equivalence must be checked; do not replace skill activation by pasting its text. |
| Execution harness | [Cline](https://docs.cline.bot/usage/cli-overview) | CLI automation exists; native configuration, permissions, skills and event accounting need separate verification. |
| Execution harness | [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills) | Native SKILL.md support. Usage, billing model and endpoint control require adapter validation. |
| Provider proxy | [opencodex / ocx](https://github.com/lidge-jun/opencodex) | Bridges Codex/Claude Code to other providers. Keep the original execution harness; evaluate this as a transport option. Downstream retries, model identity, usage and cost must remain visible. Do not automatically run setup commands that rewrite global settings. |
| Provider proxy / SDK | [LiteLLM](https://docs.litellm.ai/) | API normalization, provider routing, proxy usage tracking and budgets. The SDK is already a harness-opt dependency; a separately deployed proxy can be a configured endpoint after compatibility checks. |
| Model server | [Ollama](https://docs.ollama.com/api/openai-compatibility) | Local inference, model listing, tools and parts of OpenAI APIs. Responses support is stateless. Verify each model's tools/effort/context/usage before experiments; zero API charges do not include hardware/electricity costs. |

Implementation direction: add execution adapters separately from transport/model
support. A shared SKILL.md is useful, but cannot itself preserve another harness's
settings, native skill/plugin activation, permissions or usage events. OpenCode is
a practical next adapter to evaluate because a local CLI and native skills exist;
this ordering is an engineering judgment, not a measured performance ranking.

Bundled runtime code, skill instructions and static patterns remain inside the
plugin. Generated cases and reports are private run state, kept outside the target
workspace so snapshots never recursively include their own output.
