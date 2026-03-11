from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from trace_observability import (
    find_similar_incidents,
    refresh_docs_from_path,
    refresh_trace_from_path,
)

TraceStoreFactory = Callable[[str | None], Any]

_trace_store_factory: TraceStoreFactory | None = None
_trace_refresh_state_default: Path | None = None
_docs_refresh_state_default: Path | None = None


def configure_trace_tools(
    trace_store_factory: TraceStoreFactory,
    trace_refresh_state_default: Path,
    docs_refresh_state_default: Path,
) -> None:
    global _trace_store_factory
    global _trace_refresh_state_default, _docs_refresh_state_default
    _trace_store_factory = trace_store_factory
    _trace_refresh_state_default = trace_refresh_state_default
    _docs_refresh_state_default = docs_refresh_state_default


def _require(name: str, value: Any) -> Any:
    if value is None:
        raise RuntimeError(f"{name} is not configured")
    return value


def _parse_csv_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def record_tool_trace(
    run_id: str,
    tool_name: str,
    status: str,
    summary: str,
    error_text: str = "",
    elapsed_ms: float = 0.0,
    scenario_id: str = "adhoc",
    trace_db_path: str = "",
) -> dict[str, Any]:
    """Append one MCP tool trace record to local trace store."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    store = trace_store_factory(trace_db_path or None)
    rec = store.append(
        {
            "run_id": run_id,
            "tool_name": tool_name,
            "status": status,
            "summary": summary,
            "error_text": error_text,
            "elapsed_ms": float(elapsed_ms),
            "scenario_id": scenario_id,
        }
    )
    return {"ok": True, "trace_path": str(store.path), "record": rec}


def similar_incidents(
    query_text: str,
    top_k: int = 5,
    min_score: float = 0.0,
    status: str = "error",
    tool_name: str = "",
    scenario_id: str = "",
    start_time_utc: str = "",
    end_time_utc: str = "",
    trace_db_path: str = "",
) -> dict[str, Any]:
    """Find semantically similar historical incidents."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    store = trace_store_factory(trace_db_path or None)
    results = find_similar_incidents(
        store=store,
        query_text=query_text,
        top_k=top_k,
        min_score=min_score,
        status=status or None,
        tool_name=tool_name or None,
        scenario_id=scenario_id or None,
        start_time_utc=start_time_utc or None,
        end_time_utc=end_time_utc or None,
    )
    return {
        "ok": True,
        "query_text": query_text,
        "count": len(results),
        "results": results,
    }


def refresh_trace_path(
    source_path: str,
    trace_db_path: str = "",
    refresh_state_path: str = "",
    scenario_id: str = "refresh",
) -> dict[str, Any]:
    """Incrementally ingest new lines from source path into trace store."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    trace_refresh_state_default = _require(
        "trace_refresh_state_default", _trace_refresh_state_default
    )
    store = trace_store_factory(trace_db_path or None)
    state_path = (
        Path(refresh_state_path)
        if refresh_state_path
        else trace_refresh_state_default
    )
    result = refresh_trace_from_path(
        store=store,
        source_path=Path(source_path),
        state_path=state_path,
        scenario_id=scenario_id,
    )
    return {
        **result,
        "trace_path": str(store.path),
        "state_path": str(state_path),
    }


def refresh_docs_path(
    source_dir: str = "./docs",
    trace_db_path: str = "",
    refresh_state_path: str = "",
    scenario_id: str = "knowledge",
    include_extensions: str = ".md,.py,.rs,.toml,.json,.yaml,.yml",
    exclude_dir_names: str = ".git,.idea,.pytest_cache,.venv,__pycache__,node_modules,target",
    exclude_path_parts: str = "tests/artifacts",
    max_file_bytes: int = 200000,
) -> dict[str, Any]:
    """Incrementally ingest project docs, code, and config files."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    docs_refresh_state_default = _require(
        "docs_refresh_state_default", _docs_refresh_state_default
    )
    store = trace_store_factory(trace_db_path or None)
    state_path = (
        Path(refresh_state_path)
        if refresh_state_path
        else docs_refresh_state_default
    )
    result = refresh_docs_from_path(
        store=store,
        source_dir=Path(source_dir),
        state_path=state_path,
        scenario_id=scenario_id,
        include_extensions=_parse_csv_set(include_extensions),
        exclude_dir_names=_parse_csv_set(exclude_dir_names),
        exclude_path_parts=_parse_csv_set(exclude_path_parts),
        max_file_bytes=max_file_bytes,
    )
    return {
        **result,
        "trace_path": str(store.path),
        "state_path": str(state_path),
    }


def register_trace_tools(mcp: FastMCP) -> None:
    mcp.tool()(record_tool_trace)
    mcp.tool()(similar_incidents)
    mcp.tool()(refresh_trace_path)
    mcp.tool()(refresh_docs_path)
