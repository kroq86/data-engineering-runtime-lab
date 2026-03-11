from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_engine_runtime import EngineOps


def register_engine_tools(mcp: FastMCP, ops: EngineOps) -> dict[str, Any]:
    @mcp.tool()
    def init_engine(
        root_dir: str = "./tests/artifacts/mcp/engine_data",
        table: str = "orders",
    ) -> dict[str, Any]:
        """Initialize persistent engine storage."""
        return ops.init_engine(root_dir=root_dir, table=table)

    @mcp.tool()
    def insert_row(
        root_dir: str = "./tests/artifacts/mcp/engine_data",
        table: str = "orders",
        order_id: int = 1,
        customer_id: int = 4242,
        amount: int = 10,
    ) -> dict[str, Any]:
        """Insert one row into the persistent engine."""
        return ops.insert_row(
            root_dir=root_dir,
            table=table,
            order_id=order_id,
            customer_id=customer_id,
            amount=amount,
        )

    @mcp.tool()
    def upsert_row(
        root_dir: str = "./tests/artifacts/mcp/engine_data",
        table: str = "orders",
        order_id: int = 1,
        customer_id: int = 4242,
        amount: int = 20,
    ) -> dict[str, Any]:
        """Upsert one row by order_id."""
        return ops.upsert_row(
            root_dir=root_dir,
            table=table,
            order_id=order_id,
            customer_id=customer_id,
            amount=amount,
        )

    @mcp.tool()
    def create_index(
        root_dir: str = "./tests/artifacts/mcp/engine_data",
        table: str = "orders",
    ) -> dict[str, Any]:
        """Create customer index for engine table."""
        return ops.create_index(root_dir=root_dir, table=table)

    @mcp.tool()
    def explain_customer(
        root_dir: str = "./tests/artifacts/mcp/engine_data",
        table: str = "orders",
        customer_id: int = 4242,
    ) -> dict[str, Any]:
        """Run EXPLAIN ANALYZE style output by customer filter."""
        return ops.explain_customer(
            root_dir=root_dir, table=table, customer_id=customer_id
        )

    @mcp.tool()
    def reindex_project(
        root_dir: str = "./tests/artifacts/mcp/engine_data",
        table: str = "orders",
    ) -> dict[str, Any]:
        """Re-index this project dataset (engine_cli index)."""
        return create_index(root_dir=root_dir, table=table)

    @mcp.tool()
    def run_e2e_flow(
        root_dir: str = "./tests/artifacts/e2e/data",
    ) -> dict[str, Any]:
        """Execute full MiniPG + MiniDatabricks + DuckDB end-to-end flow."""
        return ops.run_e2e_flow(root_dir=root_dir)

    return {
        "init_engine": init_engine,
        "insert_row": insert_row,
        "upsert_row": upsert_row,
        "create_index": create_index,
        "explain_customer": explain_customer,
        "reindex_project": reindex_project,
        "run_e2e_flow": run_e2e_flow,
    }
