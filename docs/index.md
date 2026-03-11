---
layout: default
title: Mini Data Engine Lab
description: End-to-end mini data platform with MiniPG, MiniDatabricks flow, DuckDB validation, and MCP adapter tools.
keywords: mini data engine, mcp server, duckdb, rust data engineering, wal replay, transaction journal
---

# Mini Data Engine Lab

`Mini Data Engine Lab` is a compact end-to-end project for data engineering system design and implementation:

- **MiniPG-style core**: cost-based scan decisions, indexing, and explain output.
- **MiniDatabricks-style flow**: bronze/silver transform simulation.
- **DuckDB integration**: analytical validation over persisted snapshots.
- **MCP tools**: operational control through an MCP server (`mini-data-engine`).
- **Transactional safety**: checkpointing, WAL replay, tx scopes, conflict detection, and rollback journals.

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

## Why this project

This repository is built to be a practical bridge between architecture interviews and runnable systems code:

- reason about write-path reliability and replay,
- benchmark mixed workloads with measurable SLOs,
- orchestrate the stack with an MCP adapter.

## Links

- Source and setup details: see `README.md`
- License: MIT (`LICENSE`)
