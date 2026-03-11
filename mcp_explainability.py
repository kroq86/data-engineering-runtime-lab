from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from trace_observability import explain_run as explain_run_impl

ToolFn = Callable[..., dict[str, Any]]
TraceStoreFactory = Callable[[str | None], Any]

_trace_store_factory: TraceStoreFactory | None = None
_init_engine: ToolFn | None = None
_insert_row: ToolFn | None = None
_create_index: ToolFn | None = None
_explain_customer: ToolFn | None = None
_run_e2e_flow: ToolFn | None = None


def configure_explainability_tools(
    trace_store_factory: TraceStoreFactory,
    init_engine: ToolFn,
    insert_row: ToolFn,
    create_index: ToolFn,
    explain_customer: ToolFn,
    run_e2e_flow: ToolFn,
) -> None:
    global _trace_store_factory, _init_engine, _insert_row
    global _create_index, _explain_customer, _run_e2e_flow
    _trace_store_factory = trace_store_factory
    _init_engine = init_engine
    _insert_row = insert_row
    _create_index = create_index
    _explain_customer = explain_customer
    _run_e2e_flow = run_e2e_flow


def _require(name: str, value: Any) -> Any:
    if value is None:
        raise RuntimeError(f"{name} is not configured")
    return value


def _trace_summary(result: dict[str, Any]) -> str:
    if result.get("stdout"):
        return str(result["stdout"])[:300]
    if result.get("stderr"):
        return str(result["stderr"])[:300]
    return "step completed"


def explain_run(
    run_id: str,
    trace_db_path: str = "",
    max_timeline_events: int = 20,
) -> dict[str, Any]:
    """Explain one recorded run_id from the local trace store."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    store = trace_store_factory(trace_db_path or None)
    result = explain_run_impl(
        store=store,
        run_id=run_id,
        max_timeline_events=max_timeline_events,
    )
    return {**result, "trace_path": str(store.path)}


def demo_explain_run(
    root_dir: str = "./tests/artifacts/mcp/explain_demo",
    table: str = "orders",
    customer_id: int = 4242,
    trace_db_path: str = "",
) -> dict[str, Any]:
    """Run a traced demo flow, then explain the run immediately."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    init_engine = _require("init_engine", _init_engine)
    insert_row = _require("insert_row", _insert_row)
    create_index = _require("create_index", _create_index)
    explain_customer = _require("explain_customer", _explain_customer)

    store = trace_store_factory(trace_db_path or None)
    run_id = f"demo-explain-{int(time.time() * 1000)}"
    scenario_id = "explain_demo"
    demo_root = Path(root_dir) / run_id
    steps: list[tuple[str, dict[str, Any]]] = [
        ("init_engine", init_engine(root_dir=str(demo_root), table=table)),
        (
            "insert_row",
            insert_row(
                root_dir=str(demo_root),
                table=table,
                order_id=1,
                customer_id=customer_id,
                amount=10,
            ),
        ),
        ("create_index", create_index(root_dir=str(demo_root), table=table)),
        (
            "explain_customer",
            explain_customer(
                root_dir=str(demo_root),
                table=table,
                customer_id=customer_id,
            ),
        ),
    ]

    for tool_name, result in steps:
        store.append(
            {
                "run_id": run_id,
                "tool_name": tool_name,
                "status": "ok" if result.get("ok", False) else "error",
                "summary": _trace_summary(result),
                "error_text": str(result.get("stderr", "")),
                "elapsed_ms": float(result.get("elapsed_ms", 0.0)),
                "scenario_id": scenario_id,
                "source_kind": "demo_run",
                "source_path": str(demo_root),
            }
        )

    explanation = explain_run_impl(store=store, run_id=run_id)
    return {
        "ok": explanation.get("ok", False),
        "run_id": run_id,
        "root_dir": str(demo_root),
        "trace_path": str(store.path),
        "steps": [{name: result} for name, result in steps],
        "explanation": explanation,
    }


def demo_explain_run_failure(
    root_dir: str = "./tests/artifacts/mcp/explain_demo_failure",
    table: str = "orders",
    trace_db_path: str = "",
) -> dict[str, Any]:
    """Run a traced failing flow, then explain the failed run immediately."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    init_engine = _require("init_engine", _init_engine)
    run_e2e_flow = _require("run_e2e_flow", _run_e2e_flow)

    store = trace_store_factory(trace_db_path or None)
    run_id = f"demo-explain-failure-{int(time.time() * 1000)}"
    scenario_id = "explain_demo_failure"
    demo_root = Path(root_dir) / run_id
    blocked_root = demo_root / "blocked_root"
    blocked_root.parent.mkdir(parents=True, exist_ok=True)
    blocked_root.write_text("blocked path for failure demo", encoding="utf-8")

    steps: list[tuple[str, dict[str, Any]]] = [
        ("init_engine", init_engine(root_dir=str(blocked_root), table=table)),
        ("run_e2e_flow", run_e2e_flow(root_dir=str(blocked_root))),
    ]

    for tool_name, result in steps:
        store.append(
            {
                "run_id": run_id,
                "tool_name": tool_name,
                "status": "ok" if result.get("ok", False) else "error",
                "summary": _trace_summary(result),
                "error_text": str(result.get("stderr", "")),
                "elapsed_ms": float(result.get("elapsed_ms", 0.0)),
                "scenario_id": scenario_id,
                "source_kind": "demo_run",
                "source_path": str(blocked_root),
            }
        )

    explanation = explain_run_impl(store=store, run_id=run_id)
    return {
        "ok": explanation.get("ok", False),
        "run_id": run_id,
        "root_dir": str(blocked_root),
        "trace_path": str(store.path),
        "steps": [{name: result} for name, result in steps],
        "explanation": explanation,
    }


def register_explainability_tools(mcp: FastMCP) -> None:
    mcp.tool()(explain_run)
    mcp.tool()(demo_explain_run)
    mcp.tool()(demo_explain_run_failure)
