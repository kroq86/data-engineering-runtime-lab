# Interactive Data Systems Lab

Runnable Python and Rust implementations of PostgreSQL-like and Databricks-like system internals.

This repository is a compact, local-first lab for exploring:

- heap storage, B-tree indexes, and planner decisions,
- WAL/checkpoint style persistence and replay,
- Delta-style versioning and time-travel snapshots,
- workflow DAG execution, event logs, idempotency, and single-write-path design,
- programmatic access through an MCP adapter layer.

## Who This Is For

- Data engineers who want to understand what sits underneath warehouses and query engines.
- Platform and infrastructure engineers teaching or learning storage and execution fundamentals.
- Teams building onboarding, workshops, or demos around modern data system internals.

## What This Project Actually Contains

This folder contains educational Python and Rust demos:

- `mini_pg_like.py` - PostgreSQL-like toy engine (heap table, B-tree index, cost-based planner, EXPLAIN ANALYZE style output).
- `mini_databricks_clone.py` - Databricks-like toy platform (Delta-style versioning, Spark-like partitions, workflow DAG, SQL warehouse, ML tracking, catalog, single write path with events/idempotency).
- `src/bin/mini_pg_like.rs` - Rust/Cargo PostgreSQL-like demo.
- `src/bin/mini_databricks_clone.rs` - Rust/Cargo Databricks-like demo.
- `src/lib.rs` + `src/common.rs` + `src/pg.rs` - shared Rust core modules used by both binaries.

## Why It Exists

Most explanations of data systems stop at diagrams. This lab is meant to be runnable:

- inspect how heap storage and B-tree indexing affect plan choice,
- see append/upsert/checkpoint flows rather than just reading about them,
- trace a single-write-path architecture with canonical events and idempotency,
- compare Python and Rust implementations of the same ideas,
- automate the lab through MCP instead of only using ad hoc scripts.

## Requirements

- Python 3.10+ (tested with Python 3.14)

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependency:

```bash
python -m pip install "psycopg[binary]"
```

## Run

Run the PostgreSQL-like demo:

```bash
.venv/bin/python mini_pg_like.py
```

Run the Databricks-like demo:

```bash
.venv/bin/python mini_databricks_clone.py
```

Run Rust/Cargo PostgreSQL-like demo:

```bash
cargo run --bin mini_pg_like
```

Run Rust/Cargo Databricks-like demo:

```bash
cargo run --bin mini_databricks_clone
```

Run full end-to-end flow (MiniPG + MiniDatabricks + DuckDB):

```bash
cargo run --bin e2e_flow
```

## Quick Start

Run the full end-to-end flow:

```bash
cargo run --bin e2e_flow
```

Run the core demos:

```bash
.venv/bin/python mini_pg_like.py
.venv/bin/python mini_databricks_clone.py
cargo run --bin mini_pg_like
cargo run --bin mini_databricks_clone
```

## Architecture Themes

- PostgreSQL-like internals: heap tables, B-tree indexes, selectivity, planner cost tradeoffs.
- Databricks-like internals: Delta-style commits, workflow DAGs, catalog concepts, bronze-to-silver style transforms.
- Reliability discipline: deterministic transitions, idempotency, replay, canonical event logs, one write path.
- Productization path: persistent engine CLI, transaction demo, recovery commands, Docker packaging.

## MCP Adapter Layer

This repo also includes a minimal MCP server that wraps the lab operations:

- `mcp_engine_server.py`
- Cursor config: `.cursor/mcp.json`

Tools exposed by MCP:
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
- `demo_explain_run_failure`
- `demo_explain_semantic_failure`
- `demo_explain_idempotency_conflict`
- `demo_explain_concurrency_failure_storm`
- `explain_regression_suite`
- `similar_incidents`
- `refresh_trace_path`
- `refresh_docs_path`
- `capture_roi_baseline`
- `report_drift_bug`
- `decision_gate`

If Cursor MCP auto-discovery is enabled, restart Cursor and connect `mini-data-engine`.
Default MCP runtime data paths are under `tests/artifacts/mcp/*`.

Fastest way to see the new explainability use case in action through MCP:

```text
demo_explain_run
```

That single tool call creates a traced run, records step-level events under one `run_id`,
and returns an explanation with:

- ordered timeline
- tool path
- total elapsed time
- failure summary if anything breaks

You can then replay the same explanation directly with:

```text
explain_run(run_id="...")
```

## Explain Regression Suite

Use `explain_regression_suite` when you want regression checks to run through MCP and come back as explainable run summaries instead of isolated test output.

The suite drives the current validation surface through the MCP layer, attaches `run_id` traces, and returns explain output for each check so regressions can be inspected with the same mechanism used for runtime incidents.

It currently runs:

- Python unit tests via `python -m unittest discover`
- Rust tests via `cargo test`, including the current `engine_cli` integration tests
- `health_check`
- `benchmark_calls`
- `scenario_load_test`
- explainability control demos

The explainability demos intentionally include both positive and negative controls:

- `demo_explain_run` as `expected_success`
- `demo_explain_run_failure` as `expected_failure`
- `demo_explain_semantic_failure` as `expected_failure`
- `demo_explain_idempotency_conflict` as `expected_failure`
- `demo_explain_concurrency_failure_storm` as `expected_failure`

That means the suite is not only checking that the happy path stays green. It also checks that the explain layer still classifies and summarizes known failure classes correctly.

The current regression surface covers:

- happy-path traced execution
- runtime/path failures
- semantic data validation failures
- idempotency conflict failures
- concurrency and failure-storm control scenarios
- sampled benchmark and scenario SLO regressions

Fastest MCP call for the full regression bundle:

```text
explain_regression_suite
```

Use it as the top-level MCP regression entrypoint when you want one answer that includes:

- which checks passed
- which failures were expected controls
- explain summaries for each traced run
- early signals that a latency or behavior regression appeared

The MCP layer is an access interface, not the core product idea. The core of the repository is the runnable lab itself.

Product note:
- [`PRODUCT_NOTE_RUNTIME_EXPLAINABILITY.md`](/Users/ll/Documents/data-engineering-runtime-lab/PRODUCT_NOTE_RUNTIME_EXPLAINABILITY.md)
  Short note describing the runtime explainability use case, the required signals, and the `explain_run` MVP.
- [`EXPLAIN_REGRESSION_SUITE_FEASIBILITY.md`](/Users/ll/Documents/data-engineering-runtime-lab/EXPLAIN_REGRESSION_SUITE_FEASIBILITY.md)
  Short article describing what this repository validated about explain-first regression suites and where the current denominator still stays narrow.

Run persistent engine CLI (productization path):

```bash
# Initialize storage
cargo run --bin engine_cli -- init ./tests/artifacts/engine/data orders

# Insert and upsert (WAL append)
cargo run --bin engine_cli -- insert ./tests/artifacts/engine/data orders 1 4242 50
cargo run --bin engine_cli -- upsert ./tests/artifacts/engine/data orders 1 4242 55

# Build index and explain
cargo run --bin engine_cli -- index ./tests/artifacts/engine/data orders
cargo run --bin engine_cli -- explain ./tests/artifacts/engine/data orders 4242

# Write snapshot and truncate WAL
cargo run --bin engine_cli -- checkpoint ./tests/artifacts/engine/data orders

# Transaction simulation: begin/commit/rollback semantics,
# per-table write lock, snapshot read, and conflict detection
cargo run --bin engine_cli -- tx-demo ./tests/artifacts/engine/data orders

# Crash/restart recovery for transaction journals
cargo run --bin engine_cli -- tx-recovery-list ./tests/artifacts/engine/data orders
cargo run --bin engine_cli -- tx-recovery-commit ./tests/artifacts/engine/data orders <tx_id>
cargo run --bin engine_cli -- tx-recovery-rollback ./tests/artifacts/engine/data orders <tx_id>
```

## What You Should See

- In `mini_pg_like.py`: selective predicate switches to `Index Scan`; non-selective stays `Seq Scan`.
- In `mini_databricks_clone.py`: layer-by-layer demo output, workflow DAG order/metrics, and canonical events count from the single write path.
- In `mini_pg_like` (Rust): same planner behavior with shared core modules.
- In `mini_databricks_clone` (Rust): same layered demo using shared Rust library code.
- In `engine_cli` (Rust): persistent snapshot + WAL replay flow with simple operational commands.
- In `engine_cli tx-demo`: explicit transaction scopes, snapshot reads, per-table write lock, and concurrent upsert conflict detection.
- In `engine_cli tx-recovery-*`: staged transaction operations survive process restarts via per-transaction journal files and can be committed or rolled back explicitly.
- In `e2e_flow`: one command runs write path, checkpoint, bronze->silver transform, planner explain, and DuckDB SQL validation on persisted data.

## Technical Design Backbone

[`TECHNICAL_DESIGN_GENERIC.md`](./TECHNICAL_DESIGN_GENERIC.md) captures the architectural discipline behind the code:

- cross-layer reasoning (`Idea -> API -> Runtime -> Storage -> Perf`),
- deterministic state transitions,
- event-first design,
- adapter contracts,
- DAG-driven orchestration,
- measurable go/no-go criteria.

It is not a separate product claim. It is the review and implementation spine used across the lab.

## Docker package (pull and run on another Mac)

Image is published to GHCR:

- `ghcr.io/kroq86/data-engineering-runtime-lab:latest`

Pull:

```bash
docker pull ghcr.io/kroq86/data-engineering-runtime-lab:latest
```

Use in Cursor MCP config (example):

```json
{
  "mcpServers": {
    "mini-data-engine": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v",
        "${workspaceFolder}/tests/artifacts:/app/tests/artifacts",
        "ghcr.io/kroq86/data-engineering-runtime-lab:latest"
      ]
    }
  }
}
```
