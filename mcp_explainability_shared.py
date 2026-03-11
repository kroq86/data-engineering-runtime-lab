from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from trace_observability import explain_run as explain_run_impl

ToolFn = Callable[..., dict[str, Any]]
TraceStoreFactory = Callable[[str | None], Any]


@dataclass
class ExplainabilityContext:
    trace_store_factory: TraceStoreFactory | None = None
    init_engine: ToolFn | None = None
    insert_row: ToolFn | None = None
    create_index: ToolFn | None = None
    explain_customer: ToolFn | None = None
    run_e2e_flow: ToolFn | None = None
    health_check: ToolFn | None = None
    benchmark_calls: ToolFn | None = None
    scenario_load_test: ToolFn | None = None
    workspace: Path | None = None
    engine_bin: Path | None = None


CONTEXT = ExplainabilityContext()


def configure_explainability_tools(
    trace_store_factory: TraceStoreFactory,
    init_engine: ToolFn,
    insert_row: ToolFn,
    create_index: ToolFn,
    explain_customer: ToolFn,
    run_e2e_flow: ToolFn,
    health_check: ToolFn | None = None,
    benchmark_calls: ToolFn | None = None,
    scenario_load_test: ToolFn | None = None,
    workspace: Path | None = None,
    engine_bin: Path | None = None,
) -> None:
    CONTEXT.trace_store_factory = trace_store_factory
    CONTEXT.init_engine = init_engine
    CONTEXT.insert_row = insert_row
    CONTEXT.create_index = create_index
    CONTEXT.explain_customer = explain_customer
    CONTEXT.run_e2e_flow = run_e2e_flow
    CONTEXT.health_check = health_check
    CONTEXT.benchmark_calls = benchmark_calls
    CONTEXT.scenario_load_test = scenario_load_test
    CONTEXT.workspace = workspace
    CONTEXT.engine_bin = engine_bin


def require(name: str, value: Any) -> Any:
    if value is None:
        raise RuntimeError(f"{name} is not configured")
    return value


def trace_summary(result: dict[str, Any]) -> str:
    if result.get("stdout"):
        return str(result["stdout"])[:300]
    if result.get("stderr"):
        return str(result["stderr"])[:300]
    return "step completed"


def demo_actual_effects(tool_name: str) -> str:
    if tool_name == "init_engine":
        return "engine storage initialized"
    if tool_name == "insert_row":
        return "one row inserted into orders"
    if tool_name == "create_index":
        return "customer_id index available"
    if tool_name == "explain_customer":
        return "planner output captured for customer filter"
    if tool_name == "run_e2e_flow":
        return "e2e runtime execution attempted"
    if tool_name == "validate_semantic_rules":
        return "business-rule validation executed over persisted WAL"
    if tool_name == "write_core_execute":
        return "write core executed command through idempotency boundary"
    if tool_name == "tx_demo_conflict":
        return "concurrent transaction path exercised"
    if tool_name == "failure_storm":
        return "parallel failure burst exercised"
    return "step executed"


def semantic_validation_result(root_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    wal_path = root_dir / "wal.log"
    if not wal_path.exists():
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "wal.log not found for semantic validation",
            "command": "validate_semantic_rules",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    negative_rows: list[str] = []
    for line in wal_path.read_text(encoding="utf-8").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            continue
        amount = int(parts[3])
        if amount < 0:
            negative_rows.append(line)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    if negative_rows:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": (
                "semantic validation failed: negative amount rows detected: "
                + "; ".join(negative_rows)
            ),
            "command": "validate_semantic_rules",
            "elapsed_ms": elapsed_ms,
        }
    return {
        "ok": True,
        "returncode": 0,
        "stdout": "semantic validation passed",
        "stderr": "",
        "command": "validate_semantic_rules",
        "elapsed_ms": elapsed_ms,
    }


def write_core_result(fn: Callable[[], dict[str, Any]], command: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = fn()
        return {
            "ok": True,
            "returncode": 0,
            "stdout": str(result),
            "stderr": "",
            "command": command,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as err:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": str(err),
            "command": command,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def command_result(
    cmd: list[str],
    command_name: str,
    cwd: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "command": command_name,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def append_explain_trace(
    store: Any,
    run_id: str,
    scenario_id: str,
    source_path: str,
    tool_name: str,
    result: dict[str, Any],
    decision_reason: str,
    actual_effects: str,
    retry_classification: str = "not_applicable",
) -> None:
    store.append(
        {
            "run_id": run_id,
            "correlation_id": run_id,
            "tool_name": tool_name,
            "status": "ok" if result.get("ok", False) else "error",
            "summary": trace_summary(result),
            "error_text": str(result.get("stderr", "")),
            "attempt": 1,
            "retry_classification": retry_classification,
            "decision_reason": decision_reason,
            "actual_effects": actual_effects,
            "elapsed_ms": float(result.get("elapsed_ms", 0.0)),
            "scenario_id": scenario_id,
            "source_kind": "demo_run",
            "source_path": source_path,
        }
    )


def explain_run(
    run_id: str,
    trace_db_path: str = "",
    max_timeline_events: int = 20,
) -> dict[str, Any]:
    """Explain one recorded run_id from the local trace store."""
    trace_store_factory = require("trace_store_factory", CONTEXT.trace_store_factory)
    store = trace_store_factory(trace_db_path or None)
    result = explain_run_impl(
        store=store,
        run_id=run_id,
        max_timeline_events=max_timeline_events,
    )
    return {**result, "trace_path": str(store.path)}
