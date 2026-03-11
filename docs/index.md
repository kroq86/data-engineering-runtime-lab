---
layout: default
title: Mini Data Engine Lab
description: Interactive Data Systems Lab with runnable PostgreSQL-like and Databricks-like internals in Python and Rust.
keywords: interactive data systems lab, postgres internals, databricks internals, b-tree index, query planner, delta lake concepts, event log, idempotency, rust, python
---

# Mini Data Engine Lab

`Mini Data Engine Lab` is an **Interactive Data Systems Lab**:

- runnable PostgreSQL-like and Databricks-like demos,
- compact Python and Rust implementations of storage and execution ideas,
- a local-first sandbox for indexes, planners, checkpoints, workflows, and event logs,
- an MCP access layer for automation and agent-driven exploration.

## Who This Is For

- Data engineers learning how modern data systems behave under the hood.
- Platform and infrastructure engineers teaching storage, execution, and write-path fundamentals.
- Teams building onboarding labs, workshops, or demos around data platform architecture.

## What You Can Explore

- Heap tables and B-tree indexes.
- Planner decisions such as `Seq Scan` versus `Index Scan`.
- WAL/checkpoint style persistence and replay.
- Delta-style append and merge-upsert version history.
- Workflow DAG execution and single-write-path architecture.
- Canonical events, idempotency, retries, and deterministic transitions.

## GitHub

- Repository: [github.com/kroq86/data-engineering-runtime-lab](https://github.com/kroq86/data-engineering-runtime-lab)
- Owner: [@kroq86](https://github.com/kroq86)
- If this project is useful, please give it a star: [Star the repository](https://github.com/kroq86/data-engineering-runtime-lab/stargazers)

## Quick Start

```bash
cargo run --bin e2e_flow
```

## Core Components

- `mini_pg_like.py` and `src/bin/mini_pg_like.rs`
  PostgreSQL-like demos with heap storage, B-tree indexes, and planner output.
- `mini_databricks_clone.py` and `src/bin/mini_databricks_clone.rs`
  Databricks-like demos with Delta-style versioning, workflows, and event-driven write paths.
- `engine_cli` and `e2e_flow`
  Persistent engine operations, checkpointing, replay, and end-to-end validation.
- `TECHNICAL_DESIGN_GENERIC.md`
  The architecture backbone used to keep the lab deterministic and reviewable.

## MCP Access Layer

The project also exposes tools via `mcp_engine_server.py`:

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
- `explain_run`
- `demo_explain_run`
- `similar_incidents`
- `refresh_trace_path`
- `refresh_docs_path`
- `capture_roi_baseline`
- `report_drift_bug`
- `decision_gate`

This MCP layer is a programmable interface to the lab, not the primary identity of the project.

Quick MCP demo:
- call `demo_explain_run`
- it creates a traced engine run and immediately returns a structured explanation for that `run_id`

Product note:
- [Runtime Explainability Product Note](./product-note.html)
  Short note describing the incident explanation use case, the signals to store, and the `explain_run` MVP.
- [Explain-First Regression Suite Feasibility](./explain-regression-suite-feasibility.html)
  Article describing what the repository validated about traced regression bundles, expected-failure controls, and current denominator limits.

## Why This Project

This repository is built to bridge architecture diagrams and runnable systems code:

- learn core data system mechanics without needing full PostgreSQL, Spark, or Databricks deployments,
- compare Python and Rust implementations of the same ideas,
- turn storage and execution concepts into something you can run, inspect, and automate.

## Links

- GitHub repository: [data-engineering-runtime-lab](https://github.com/kroq86/data-engineering-runtime-lab)
- Open issues / feature requests: [Issues](https://github.com/kroq86/data-engineering-runtime-lab/issues)
- Source and setup details: [README.md](https://github.com/kroq86/data-engineering-runtime-lab/blob/main/README.md)
- License: MIT (`LICENSE`)
