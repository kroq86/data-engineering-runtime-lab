from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from mini_pg_like import EventLog, InsertAdapter, MiniPostgresLikeDB, WriteCore
from trace_observability import explain_run as explain_run_impl

ToolFn = Callable[..., dict[str, Any]]
TraceStoreFactory = Callable[[str | None], Any]

_trace_store_factory: TraceStoreFactory | None = None
_init_engine: ToolFn | None = None
_insert_row: ToolFn | None = None
_create_index: ToolFn | None = None
_explain_customer: ToolFn | None = None
_run_e2e_flow: ToolFn | None = None
_health_check: ToolFn | None = None
_benchmark_calls: ToolFn | None = None
_scenario_load_test: ToolFn | None = None
_workspace: Path | None = None


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
) -> None:
    global _trace_store_factory, _init_engine, _insert_row
    global _create_index, _explain_customer, _run_e2e_flow
    global _health_check, _benchmark_calls, _scenario_load_test, _workspace
    _trace_store_factory = trace_store_factory
    _init_engine = init_engine
    _insert_row = insert_row
    _create_index = create_index
    _explain_customer = explain_customer
    _run_e2e_flow = run_e2e_flow
    _health_check = health_check
    _benchmark_calls = benchmark_calls
    _scenario_load_test = scenario_load_test
    _workspace = workspace


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


def _demo_actual_effects(tool_name: str, result: dict[str, Any]) -> str:
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
    return "step executed"


def _semantic_validation_result(root_dir: Path) -> dict[str, Any]:
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


def _write_core_result(fn: Callable[[], dict[str, Any]], command: str) -> dict[str, Any]:
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


def _command_result(
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


def _append_explain_trace(
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
            "summary": _trace_summary(result),
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
                "correlation_id": run_id,
                "tool_name": tool_name,
                "status": "ok" if result.get("ok", False) else "error",
                "summary": _trace_summary(result),
                "error_text": str(result.get("stderr", "")),
                "attempt": 1,
                "retry_classification": "not_applicable",
                "decision_reason": (
                    "demo flow step completed"
                    if result.get("ok", False)
                    else "demo flow step failed"
                ),
                "actual_effects": _demo_actual_effects(tool_name, result),
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
                "correlation_id": run_id,
                "tool_name": tool_name,
                "status": "ok" if result.get("ok", False) else "error",
                "summary": _trace_summary(result),
                "error_text": str(result.get("stderr", "")),
                "attempt": 1,
                "retry_classification": "non_retryable"
                if not result.get("ok", False)
                else "not_applicable",
                "decision_reason": (
                    "blocked path intentionally triggers runtime directory error"
                ),
                "actual_effects": _demo_actual_effects(tool_name, result),
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


def demo_explain_semantic_failure(
    root_dir: str = "./tests/artifacts/mcp/explain_demo_semantic_failure",
    table: str = "orders",
    customer_id: int = 4242,
    trace_db_path: str = "",
) -> dict[str, Any]:
    """Run a traced semantic-corruption flow and explain the failed validation."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    init_engine = _require("init_engine", _init_engine)
    insert_row = _require("insert_row", _insert_row)

    store = trace_store_factory(trace_db_path or None)
    run_id = f"demo-explain-semantic-{int(time.time() * 1000)}"
    scenario_id = "explain_demo_semantic_failure"
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
                amount=-5,
            ),
        ),
        ("validate_semantic_rules", _semantic_validation_result(demo_root)),
    ]

    for tool_name, result in steps:
        store.append(
            {
                "run_id": run_id,
                "correlation_id": run_id,
                "tool_name": tool_name,
                "status": "ok" if result.get("ok", False) else "error",
                "summary": _trace_summary(result),
                "error_text": str(result.get("stderr", "")),
                "attempt": 1,
                "retry_classification": "non_retryable"
                if not result.get("ok", False)
                else "not_applicable",
                "decision_reason": (
                    "semantic validation failed because persisted amount was negative"
                    if tool_name == "validate_semantic_rules"
                    and not result.get("ok", False)
                    else "semantic demo step completed"
                ),
                "actual_effects": _demo_actual_effects(tool_name, result),
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


def demo_explain_idempotency_conflict(
    trace_db_path: str = "",
) -> dict[str, Any]:
    """Run a traced idempotency-conflict flow through WriteCore."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    store = trace_store_factory(trace_db_path or None)
    run_id = f"demo-explain-idempotency-{int(time.time() * 1000)}"
    scenario_id = "explain_demo_idempotency_conflict"

    db = MiniPostgresLikeDB()
    db.create_table("orders", ["order_id", "customer_id", "amount"])
    write_core = WriteCore(adapter=InsertAdapter(db), event_log=EventLog())

    first_command = {
        "run_id": f"{run_id}-1",
        "source": "mcp_demo",
        "scope": "demo",
        "idempotency_key": "orders-demo-key",
        "payload": {
            "table": "orders",
            "rows": [
                {"order_id": 1, "customer_id": 4242, "amount": 10},
            ],
        },
    }
    conflict_command = {
        "run_id": f"{run_id}-2",
        "source": "mcp_demo",
        "scope": "demo",
        "idempotency_key": "orders-demo-key",
        "payload": {
            "table": "orders",
            "rows": [
                {"order_id": 1, "customer_id": 4242, "amount": 99},
            ],
        },
    }

    steps: list[tuple[str, dict[str, Any]]] = [
        (
            "write_core_execute",
            _write_core_result(
                lambda: write_core.execute(first_command),
                "write_core.execute initial",
            ),
        ),
        (
            "write_core_execute",
            _write_core_result(
                lambda: write_core.execute(conflict_command),
                "write_core.execute conflicting_payload",
            ),
        ),
    ]

    for index, (tool_name, result) in enumerate(steps, start=1):
        is_conflict = index == 2 and not result.get("ok", False)
        store.append(
            {
                "run_id": run_id,
                "correlation_id": run_id,
                "tool_name": tool_name,
                "status": "ok" if result.get("ok", False) else "error",
                "summary": _trace_summary(result),
                "error_text": str(result.get("stderr", "")),
                "attempt": 1,
                "retry_classification": "non_retryable"
                if is_conflict
                else "not_applicable",
                "decision_reason": (
                    "idempotency key reused with different payload"
                    if is_conflict
                    else "write_core command accepted"
                ),
                "actual_effects": _demo_actual_effects(tool_name, result),
                "elapsed_ms": float(result.get("elapsed_ms", 0.0)),
                "scenario_id": scenario_id,
                "source_kind": "demo_run",
                "source_path": "write_core:demo",
            }
        )

    explanation = explain_run_impl(store=store, run_id=run_id)
    return {
        "ok": explanation.get("ok", False),
        "run_id": run_id,
        "trace_path": str(store.path),
        "steps": [{f"{name}_{idx}": result} for idx, (name, result) in enumerate(steps, start=1)],
        "explanation": explanation,
    }


def explain_regression_suite(
    root_prefix: str = "./tests/artifacts/mcp/explain_suite",
    trace_db_path: str = "",
    benchmark_iterations: int = 8,
    scenario_iterations: int = 8,
) -> dict[str, Any]:
    """Run regression checks and return explain output for each traced run."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    health_check = _require("health_check", _health_check)
    benchmark_calls = _require("benchmark_calls", _benchmark_calls)
    scenario_load_test = _require("scenario_load_test", _scenario_load_test)
    workspace = _require("workspace", _workspace)

    store = trace_store_factory(trace_db_path or None)
    root = Path(root_prefix)

    health = health_check(root_dir=str(root / "health"))
    bench = benchmark_calls(
        iterations=benchmark_iterations, root_dir=str(root / "bench")
    )
    scenario = scenario_load_test(
        iterations=scenario_iterations, root_dir=str(root / "scenario")
    )
    demo_ok = demo_explain_run(
        root_dir=str(root / "demo_ok"), trace_db_path=trace_db_path
    )
    demo_fail = demo_explain_run_failure(
        root_dir=str(root / "demo_fail"), trace_db_path=trace_db_path
    )
    semantic_fail = demo_explain_semantic_failure(
        root_dir=str(root / "semantic_fail"), trace_db_path=trace_db_path
    )
    idempotency_fail = demo_explain_idempotency_conflict(
        trace_db_path=trace_db_path
    )
    python_suite_run_id = f"python-suite-{int(time.time() * 1000)}"
    python_suite_result = _command_result(
        [
            "python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            str(workspace / "tests"),
            "-p",
            "test_*.py",
        ],
        "python_unittest_discover",
        cwd=workspace,
    )
    _append_explain_trace(
        store=store,
        run_id=python_suite_run_id,
        scenario_id="python_test_suite",
        source_path=str(workspace / "tests"),
        tool_name="python_test_suite",
        result=python_suite_result,
        decision_reason=(
            "all Python unit tests passed"
            if python_suite_result.get("ok", False)
            else "Python unit test suite reported failures"
        ),
        actual_effects="Python test discovery completed",
        retry_classification="not_applicable",
    )
    rust_suite_run_id = f"rust-suite-{int(time.time() * 1000)}"
    rust_suite_result = _command_result(
        ["cargo", "test"],
        "cargo_test",
        cwd=workspace,
    )
    _append_explain_trace(
        store=store,
        run_id=rust_suite_run_id,
        scenario_id="rust_test_suite",
        source_path=str(workspace / "tests"),
        tool_name="rust_test_suite",
        result=rust_suite_result,
        decision_reason=(
            "all Rust tests and integration tests passed"
            if rust_suite_result.get("ok", False)
            else "Rust test suite reported failures"
        ),
        actual_effects="cargo test completed across binaries and integration tests",
        retry_classification="not_applicable",
    )

    traced_checks = []
    for name, result in [
        ("python_test_suite", {"trace_run_id": python_suite_run_id, **python_suite_result}),
        ("rust_test_suite", {"trace_run_id": rust_suite_run_id, **rust_suite_result}),
        ("health_check", health),
        ("benchmark_calls", bench),
        ("scenario_load_test", scenario),
    ]:
        run_id = str(result.get("trace_run_id", ""))
        traced_checks.append(
            {
                "name": name,
                "result": result,
                "explanation": explain_run_impl(store=store, run_id=run_id)
                if run_id
                else {"ok": False, "reason": "missing trace_run_id"},
            }
        )

    return {
        "ok": True,
        "root_prefix": str(root),
        "traced_checks": traced_checks,
        "explain_demos": {
            "demo_explain_run": {
                "expectation": "expected_success",
                "explanation": demo_ok["explanation"],
            },
            "demo_explain_run_failure": {
                "expectation": "expected_failure",
                "explanation": demo_fail["explanation"],
            },
            "demo_explain_semantic_failure": {
                "expectation": "expected_failure",
                "explanation": semantic_fail["explanation"],
            },
            "demo_explain_idempotency_conflict": {
                "expectation": "expected_failure",
                "explanation": idempotency_fail["explanation"],
            },
        },
    }


def register_explainability_tools(mcp: FastMCP) -> None:
    mcp.tool()(explain_run)
    mcp.tool()(demo_explain_run)
    mcp.tool()(demo_explain_run_failure)
    mcp.tool()(demo_explain_semantic_failure)
    mcp.tool()(demo_explain_idempotency_conflict)
    mcp.tool()(explain_regression_suite)
