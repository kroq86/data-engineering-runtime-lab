---
name: "runtime-copilot"
description: "Use when the user wants to operate, diagnose, or validate the Mini Data Engine MCP runtime from Codex; prefer the MCP surface over raw shell commands, start with project_tool_catalog and project_get_defaults, then use health_check, project_run_regression, explain_run, project_compare_baseline, and related runtime tools."
---

# Runtime Copilot

Use this skill when working with the Mini Data Engine MCP server from Codex.

The goal is to treat the runtime as a self-describing operational surface, not as a pile of scripts.

## Quick start

1. Call `project_tool_catalog` to see the current MCP surface.
2. Call `project_get_defaults` to load default roots and runtime assumptions.
3. Use `health_check` for a fast smoke test.
4. Use `project_run_regression` when the user wants a release-style verdict.
5. Use `explain_run` and `similar_incidents` when diagnosing failures.

## Working rules

- Prefer MCP tools before raw shell commands when the capability already exists in MCP.
- Use shell commands only for setup gaps, file inspection, or changes outside the MCP surface.
- When summarizing runtime state, mention the exact MCP tools used.
- If the user asks what is available, answer from `project_tool_catalog`, not from memory.
- If the user asks about defaults, answer from `project_get_defaults`, not from scattered code paths.

## Recommended tool order

For discovery:
- `project_tool_catalog`
- `project_get_defaults`
- `project_manifest`
- `project_capabilities`

For health and diagnostics:
- `health_check`
- `benchmark_calls`
- `scenario_load_test`
- `explain_run`
- `similar_incidents`

For regression and release confidence:
- `project_run_regression`
- `project_capture_baseline`
- `project_compare_baseline`
- `decision_gate`

## Example requests that should trigger this skill

- "Show me what this MCP runtime can do."
- "Check whether the runtime is healthy."
- "Run the release gate and tell me if this is safe."
- "Explain why this run failed."
- "Compare current runtime behavior to the last baseline."

## Default answer shape

Keep answers operational and short:

- what was checked
- what passed or failed
- what changed
- what the next action is
