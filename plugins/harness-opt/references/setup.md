# Setup inside the skill

This is the end-user setup flow when they want to run an optimization. Reuse values
already supplied. When developing or discussing harness-opt itself, update this
flow instead of requiring the developer to supply live credentials or a real target.

1. Identify the user's current harness. Use it for real skill execution once its
   adapter is supported; never ask them to install every harness. Current adapters:
   Claude Code and Codex. OpenCode then Pi are the next priorities. Setup and catalog
   inspection are still possible elsewhere; do not claim full execution there yet.
2. Ask for a target path, or offer the bundled `examples/file-skill` demo. For the
   demo, copy that directory into a new temporary/user-selected workspace before
   running, so the installed plugin is not the experiment workspace. Consult
   `targets.md` when the user wants candidate skills. No target is needed for setup.
3. Find the bundled runtime two directories above the skill directory. Install it
   into a writable virtual environment if necessary. Do not require a repo checkout.
4. Ask which provider to use, offering an existing configuration first. OpenRouter
   has a bundled URL preset and a public price catalog. Ollama is a model server;
   its preset only prepares a local endpoint, not a verified model or free hardware.
   Other providers, including existing LiteLLM/opencodex servers, need their base URL.
5. Prepare the user's `.env` outside the installed plugin. These commands make no
   API calls, preserve unrelated settings and keep the file owner-readable only:

   ```sh
   harness-opt configure openrouter --env-file /path/to/project/.env
   harness-opt configure custom --base-url https://provider.example/v1 --env-file /path/to/project/.env
   ```

   With no key available, this creates a template and reports `needs_api_key`.
   Never ask the user to paste a secret into the agent chat. If an environment
   variable already contains the key, reference its NAME, without expanding it:

   ```sh
   harness-opt configure openrouter --env-file /path/to/project/.env --api-key-env OPENROUTER_API_KEY
   ```

   Otherwise the user can fill the file in their editor or run this command in a
   local interactive terminal; hidden input is refused in non-interactive sessions:

   ```sh
   harness-opt configure openrouter --env-file /path/to/project/.env --prompt-key
   ```

   Do not print the file or capture its secret contents. `configured` means fields
   were stored, not that authentication or model compatibility was verified.
   Existing process environment variables take precedence over file values; the
   command reports when an environment variable overrides the stored key.
6. Use `harness-opt models --env-file /path/to/project/.env` to inspect the provider
   catalog. `models --openrouter` works without a key. Catalog access can be public,
   so it does not prove key validity. Summarize relevant IDs and metadata instead of
   dumping hundreds of models. Resolve the baseline from native model/effort settings
   and let the user choose explicit overrides if needed. Do not invent availability,
   effort support, context limits or prices; missing metadata requires provider/user
   information before automated execution.
7. Ask together for the mode, final repetitions (3 recommended), dollar ceiling and
   time limit in seconds. Explain repetitions are per candidate per case, with judge
   calls in addition. Amount and time have no paid defaults. Record the user's choices
   in the CLI invocation; do not turn a previous run's allowance into new permission.
8. Show the target, native runner, provider/model/effort, mode, repetition count,
   budget and time limit, then execute once the choices are supplied. Use the CLI's
   frozen cases/report paths for review. If hooks/MCP or other prerequisites prevent
   reproducibility, report the actual blocker and request only the fixture information
   needed for that selected task. Never substitute a production connection.

A direct model API benchmark can compare answers/usage, but does not execute the
user's native tools, hooks, MCP or subagents. It must not be labeled full skill
validation. There is currently no standalone direct-API evaluation command.
