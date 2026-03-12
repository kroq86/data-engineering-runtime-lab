---
layout: default
title: Use Runtime Copilot In Codex
description: How to connect Mini Data Engine as an MCP server in Codex, install the Runtime Copilot skill, and reuse ready-made automation examples.
keywords: codex skill, codex automation, runtime copilot, MCP in Codex, model context protocol, Mini Data Engine
seo_type: article
schema_type: TechArticle
permalink: /use-in-codex/
---

# Use Runtime Copilot In Codex

This repository can be used in Codex as an MCP-connected operational surface.

The best way to think about it is:

- the MCP server is the runtime interface
- the `Runtime Copilot` skill is the operating guide
- the automation examples are repeatable workflows on top

## What To Install

This repository now includes:

- a Codex skill at [`codex/skills/runtime-copilot/SKILL.md`](https://github.com/kroq86/data-engineering-runtime-lab/blob/main/codex/skills/runtime-copilot/SKILL.md)
- skill metadata at [`codex/skills/runtime-copilot/agents/openai.yaml`](https://github.com/kroq86/data-engineering-runtime-lab/blob/main/codex/skills/runtime-copilot/agents/openai.yaml)
- automation examples in [`codex/automations/`](https://github.com/kroq86/data-engineering-runtime-lab/tree/main/codex/automations)

## 1. Connect The MCP Server

Configure Codex so that `mini-data-engine` points at the local MCP server entrypoint:

```toml
[mcp_servers.mini-data-engine]
command = "/Users/ll/Documents/data-engineering-runtime-lab/.venv/bin/python"
args = ["/Users/ll/Documents/data-engineering-runtime-lab/mcp_engine_server.py"]
```

If you prefer Docker, point Codex at the published MCP image instead.

## 2. Install The Skill

Copy the skill folder into your Codex skills directory:

```bash
mkdir -p "$HOME/.codex/skills/runtime-copilot"
cp -R /Users/ll/Documents/data-engineering-runtime-lab/codex/skills/runtime-copilot/. "$HOME/.codex/skills/runtime-copilot/"
```

After that, Codex can trigger the skill when the request is about runtime diagnostics, MCP discovery, explainability, or regression checks.

## 3. Use The Right Entry Points

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

## 4. Reuse The Automation Examples

The repo includes two ready-made automation examples:

- `codex/automations/runtime-health-check.toml`
- `codex/automations/runtime-release-gate.toml`

They are meant as templates for:

- recurring runtime smoke checks
- recurring regression and baseline checks

## 5. What A Good Codex Session Looks Like

A good Codex session usually starts with:

1. `project_tool_catalog`
2. `project_get_defaults`
3. one operational check such as `health_check` or `project_run_regression`

That keeps the interaction declarative and MCP-first instead of dropping straight into shell commands.

## Related Links

- [Runtime Copilot](./runtime-copilot.html)
- [Mini Data Engine Lab Home](./)
- [Project README](https://github.com/kroq86/data-engineering-runtime-lab/blob/main/README.md)
