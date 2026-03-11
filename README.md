# Mini Data Systems Demos

This folder contains educational Python and Rust demos:

- `mini_pg_like.py` - PostgreSQL-like toy engine (heap table, B-tree index, cost-based planner, EXPLAIN ANALYZE style output).
- `mini_databricks_clone.py` - Databricks-like toy platform (Delta-style versioning, Spark-like partitions, workflow DAG, SQL warehouse, ML tracking, catalog, single write path with events/idempotency).
- `src/bin/mini_pg_like.rs` - Rust/Cargo PostgreSQL-like demo.
- `src/bin/mini_databricks_clone.rs` - Rust/Cargo Databricks-like demo.
- `src/lib.rs` + `src/common.rs` + `src/pg.rs` - shared Rust core modules used by both binaries.

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

## MCP Adapter Layer (Cursor)

This repo now includes a minimal MCP server that wraps engine operations:

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

If Cursor MCP auto-discovery is enabled, restart Cursor and connect `mini-data-engine`.
Default MCP runtime data paths are under `tests/artifacts/mcp/*`.

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
