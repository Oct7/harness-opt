# Harness Opt plugin

This directory is a self-contained Claude Code/Codex plugin and Python package.
Install its runtime in a virtual environment:

```sh
python3 -m venv /path/to/writable/venv
/path/to/writable/venv/bin/python -m pip install .
/path/to/writable/venv/bin/harness-opt models --openrouter
```

The public OpenRouter catalog requires no API key. Paid execution requires
`HARNESS_<NAME>_BASE_URL` and `HARNESS_<NAME>_API_KEY` in `.env` or the environment,
and explicit `--budget-usd` / `--time-limit` values. Use `--help` for each command.

The shared skill is `skills/harness-opt/SKILL.md`. Full setup, pricing metadata,
verification and preview limitations: https://github.com/Oct7/harness-opt#readme.

This is a development preview. Recommendations only cover recorded environments
and generated cases; paid provider integration and external hook/MCP isolation
remain release gates. Project code is MIT licensed. Reference descriptions are
original summaries with pinned source provenance in `references/patterns.json`.
