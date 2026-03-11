---
layout: default
title: Mini Data Engine Lab
description: MCP Reliability and Observability Runtime with replayable tool operations, SLO gates, incident similarity, and migration decision guardrails.
keywords: mcp reliability, mcp observability, incident similarity, slo gates, replayable tool operations, decision gate, ai agent runtime
---

# Mini Data Engine Lab

`Mini Data Engine Lab` is an **MCP Reliability & Observability Runtime**:

- replayable tool operations and trace capture,
- measurable SLO gates for runtime health,
- semantic incident similarity for faster triage,
- migration decision guardrails based on real trigger criteria.

## Who This Is For

- Platform/SRE teams running MCP tools and needing reliability controls.
- Teams building agent workflows that need observability, replay, and regression checks.
- Engineers who want a local-first runtime lab before production cloud rollout.

## Top 3 Production Pains Solved

- **Non-reproducible MCP failures**: trace capture + replayable operations reduce guesswork.
- **No objective quality gate**: SLO-based checks (`success_rate`, p50/p95, failure breakdown) make pass/fail explicit.
- **Hard migration decisions**: `decision_gate` converts architecture discussion into measurable triggers.

## What Success Looks Like In 2 Weeks

- Baseline snapshot captured and tracked in CI.
- Incident triage uses `similar_incidents` for at least one real debugging flow.
- Decision gate reports trigger status from trace + baseline + drift bug counter.
- No regressions in `health_check`, `benchmark_calls`, and `scenario_load_test`.

## GitHub

- Repository: [github.com/kroq86/data-engineering-runtime-lab](https://github.com/kroq86/data-engineering-runtime-lab)
- Owner: [@kroq86](https://github.com/kroq86)
- If this project is useful, please give it a star: [Star the repository](https://github.com/kroq86/data-engineering-runtime-lab/stargazers)

## Quick Start

```bash
cargo run --bin e2e_flow
```

## MCP Tooling

The project exposes tools via `mcp_engine_server.py`:

- `init_engine`
- `insert_row`
- `upsert_row`
- `create_index`
- `explain_customer`
- `reindex_project`
- `run_e2e_flow`
- `health_check`
- `benchmark_calls`
- `scenario_load_test`
- `record_tool_trace`
- `similar_incidents`
- `refresh_trace_path`
- `refresh_docs_path`
- `capture_roi_baseline`
- `report_drift_bug`
- `decision_gate`

## Why this project

This repository is built to be a practical bridge between architecture interviews and runnable systems code:

- reason about write-path reliability and replay,
- benchmark mixed workloads with measurable SLOs,
- orchestrate the stack with an MCP adapter.

## Links

- GitHub repository: [data-engineering-runtime-lab](https://github.com/kroq86/data-engineering-runtime-lab)
- Open issues / feature requests: [Issues](https://github.com/kroq86/data-engineering-runtime-lab/issues)
- Source and setup details: [README.md](https://github.com/kroq86/data-engineering-runtime-lab/blob/main/README.md)
- License: MIT (`LICENSE`)
