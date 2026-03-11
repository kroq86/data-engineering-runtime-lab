from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_explainability_demos import (
    demo_explain_concurrency_failure_storm,
    demo_explain_idempotency_conflict,
    demo_explain_run,
    demo_explain_run_failure,
    demo_explain_semantic_failure,
)
from mcp_explainability_shared import configure_explainability_tools, explain_run
from mcp_explainability_suite import explain_regression_suite


def register_explainability_tools(mcp: FastMCP) -> None:
    mcp.tool()(explain_run)
    mcp.tool()(demo_explain_run)
    mcp.tool()(demo_explain_run_failure)
    mcp.tool()(demo_explain_semantic_failure)
    mcp.tool()(demo_explain_idempotency_conflict)
    mcp.tool()(demo_explain_concurrency_failure_storm)
    mcp.tool()(explain_regression_suite)
