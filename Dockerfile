FROM rust:1.85 AS builder
WORKDIR /app

COPY Cargo.toml Cargo.lock ./
COPY src ./src

RUN cargo build --release --bin engine_cli --bin e2e_flow --bin mini_pg_like --bin mini_databricks_clone

FROM python:3.12-slim AS runtime
WORKDIR /app

LABEL io.modelcontextprotocol.server.name="io.github.kroq86/mini-data-engine"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    cargo \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir mcp duckdb

# Provide a minimal duckdb CLI wrapper for Rust e2e binary expectations.
COPY scripts/duckdb_wrapper.py /usr/local/bin/duckdb
RUN chmod +x /usr/local/bin/duckdb

COPY --from=builder /app/target/release/engine_cli /app/bin/engine_cli
COPY --from=builder /app/target/release/e2e_flow /app/bin/e2e_flow
COPY --from=builder /app/target/release/mini_pg_like /app/bin/mini_pg_like
COPY --from=builder /app/target/release/mini_databricks_clone /app/bin/mini_databricks_clone
COPY . /app

ENV MINI_DATA_ENGINE_BIN_DIR=/app/bin
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "/app/mcp_engine_server.py"]
