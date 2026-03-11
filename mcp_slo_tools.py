from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from mcp_slo import (
    benchmark_calls_impl,
    capture_baseline_snapshot,
    evaluate_decision_gate,
    increment_drift_bug_counter,
    scenario_load_test_impl,
)

ToolFn = Callable[..., dict[str, Any]]

_record_tool_trace: ToolFn | None = None
_init_engine: ToolFn | None = None
_insert_row: ToolFn | None = None
_upsert_row: ToolFn | None = None
_reindex_project: ToolFn | None = None
_explain_customer: ToolFn | None = None
_run_e2e_flow: ToolFn | None = None
_trace_db_default: Path | None = None
_baseline_snapshot_default: Path | None = None
_drift_bug_counter_default: Path | None = None


def configure_slo_tools(
    record_tool_trace: ToolFn,
    init_engine: ToolFn,
    insert_row: ToolFn,
    upsert_row: ToolFn,
    reindex_project: ToolFn,
    explain_customer: ToolFn,
    run_e2e_flow: ToolFn,
    trace_db_default: Path,
    baseline_snapshot_default: Path,
    drift_bug_counter_default: Path,
) -> None:
    global _record_tool_trace, _init_engine, _insert_row, _upsert_row
    global _reindex_project, _explain_customer, _run_e2e_flow
    global _trace_db_default, _baseline_snapshot_default
    global _drift_bug_counter_default
    _record_tool_trace = record_tool_trace
    _init_engine = init_engine
    _insert_row = insert_row
    _upsert_row = upsert_row
    _reindex_project = reindex_project
    _explain_customer = explain_customer
    _run_e2e_flow = run_e2e_flow
    _trace_db_default = trace_db_default
    _baseline_snapshot_default = baseline_snapshot_default
    _drift_bug_counter_default = drift_bug_counter_default


def _require(name: str, value: Any) -> Any:
    if value is None:
        raise RuntimeError(f"{name} is not configured")
    return value


def health_check(
    root_dir: str = "./tests/artifacts/mcp/health", table: str = "orders"
) -> dict[str, Any]:
    """Run a quick MCP smoke flow and summarize status."""
    init_engine = _require("init_engine", _init_engine)
    insert_row = _require("insert_row", _insert_row)
    reindex_project = _require("reindex_project", _reindex_project)
    explain_customer = _require("explain_customer", _explain_customer)
    record_tool_trace = _require("record_tool_trace", _record_tool_trace)

    steps = [
        ("init_engine", init_engine(root_dir=root_dir, table=table)),
        (
            "insert_row",
            insert_row(
                root_dir=root_dir,
                table=table,
                order_id=1,
                customer_id=4242,
                amount=10,
            ),
        ),
        ("reindex_project", reindex_project(root_dir=root_dir, table=table)),
        (
            "explain_customer",
            explain_customer(root_dir=root_dir, table=table, customer_id=4242),
        ),
    ]
    ok = all(result.get("ok", False) for _, result in steps)
    out = {"ok": ok, "steps": [{name: result} for name, result in steps]}
    trace_run_id = f"health-{int(time.time() * 1000)}"
    record_tool_trace(
        run_id=trace_run_id,
        tool_name="health_check",
        status="ok" if ok else "error",
        summary="health_check finished",
        error_text="" if ok else "one or more health steps failed",
        elapsed_ms=0.0,
        scenario_id="health",
    )
    out["trace_run_id"] = trace_run_id
    return out


def benchmark_calls(
    iterations: int = 5,
    root_dir: str = "./tests/artifacts/mcp/bench",
    table: str = "orders",
    min_success_rate: float = 0.99,
    max_p95_ms: float = 100.0,
) -> dict[str, Any]:
    """Benchmark MCP operations with SLO-style summary metrics."""
    init_engine = _require("init_engine", _init_engine)
    insert_row = _require("insert_row", _insert_row)
    reindex_project = _require("reindex_project", _reindex_project)
    explain_customer = _require("explain_customer", _explain_customer)
    record_tool_trace = _require("record_tool_trace", _record_tool_trace)

    out = benchmark_calls_impl(
        iterations=iterations,
        root_dir=root_dir,
        table=table,
        min_success_rate=min_success_rate,
        max_p95_ms=max_p95_ms,
        init_engine=init_engine,
        insert_row=insert_row,
        reindex_project=reindex_project,
        explain_customer=explain_customer,
    )
    if not out.get("ok", False):
        return out
    trace_run_id = f"benchmark-{int(time.time() * 1000)}"
    record_tool_trace(
        run_id=trace_run_id,
        tool_name="benchmark_calls",
        status="ok" if out["slo"]["passed"] else "error",
        summary=(
            f"benchmark_calls success_rate={out['success_rate']} "
            f"p95={out['insert_p95_ms']}ms"
        ),
        error_text="; ".join(out["slo"]["violations"]),
        elapsed_ms=float(out["insert_avg_ms"]),
        scenario_id="benchmark",
    )
    out["trace_run_id"] = trace_run_id
    return out


def scenario_load_test(
    iterations: int = 10,
    root_dir: str = "./tests/artifacts/mcp/scenario",
    table: str = "orders",
    min_success_rate: float = 0.99,
    max_overall_p95_ms: float = 100.0,
    max_e2e_p95_ms: float = 500.0,
) -> dict[str, Any]:
    """
    Mixed workload load test:
    insert/upsert/explain/reindex/e2e and summary metrics.
    """
    init_engine = _require("init_engine", _init_engine)
    insert_row = _require("insert_row", _insert_row)
    upsert_row = _require("upsert_row", _upsert_row)
    explain_customer = _require("explain_customer", _explain_customer)
    reindex_project = _require("reindex_project", _reindex_project)
    run_e2e_flow = _require("run_e2e_flow", _run_e2e_flow)
    record_tool_trace = _require("record_tool_trace", _record_tool_trace)

    out = scenario_load_test_impl(
        iterations=iterations,
        root_dir=root_dir,
        table=table,
        min_success_rate=min_success_rate,
        max_overall_p95_ms=max_overall_p95_ms,
        max_e2e_p95_ms=max_e2e_p95_ms,
        init_engine=init_engine,
        insert_row=insert_row,
        upsert_row=upsert_row,
        explain_customer=explain_customer,
        reindex_project=reindex_project,
        run_e2e_flow=run_e2e_flow,
    )
    if not out.get("ok", False):
        return out
    trace_run_id = f"scenario-{int(time.time() * 1000)}"
    record_tool_trace(
        run_id=trace_run_id,
        tool_name="scenario_load_test",
        status="ok" if out["slo"]["passed"] else "error",
        summary=(
            f"scenario_load_test success_rate={out['success_rate']} "
            f"overall_p95={out['latency_ms']['overall_p95']}ms"
        ),
        error_text="; ".join(out["slo"]["violations"]),
        elapsed_ms=float(out["latency_ms"]["overall_p95"]),
        scenario_id="scenario",
    )
    out["trace_run_id"] = trace_run_id
    return out


def capture_roi_baseline(
    root_dir: str = "./tests/artifacts/mcp/baseline_runtime",
    table: str = "orders",
    benchmark_iterations: int = 5,
    scenario_iterations: int = 5,
    output_path: str = "",
) -> dict[str, Any]:
    """Capture baseline KPI snapshot for ROI Phase 0."""
    baseline_snapshot_default = _require(
        "baseline_snapshot_default", _baseline_snapshot_default
    )
    bench = benchmark_calls(
        iterations=benchmark_iterations,
        root_dir=root_dir,
        table=table,
        min_success_rate=0.9,
        max_p95_ms=2000.0,
    )
    scen = scenario_load_test(
        iterations=scenario_iterations,
        root_dir=root_dir,
        table=table,
        min_success_rate=0.9,
        max_overall_p95_ms=3000.0,
        max_e2e_p95_ms=6000.0,
    )
    snapshot_path = (
        Path(output_path) if output_path else baseline_snapshot_default
    )
    return capture_baseline_snapshot(
        output_path=snapshot_path,
        benchmark_result=bench,
        scenario_result=scen,
        kpi_targets={
            "troubleshooting_time_reduction_pct": 30,
            "retrieval_p95_ms_max": 300.0,
            "first_attempt_recovery_usefulness_pct": 70,
        },
    )


def report_drift_bug(note: str = "", counter_path: str = "") -> dict[str, Any]:
    """Increment and persist split-logic drift bug counter."""
    drift_bug_counter_default = _require(
        "drift_bug_counter_default", _drift_bug_counter_default
    )
    path = Path(counter_path) if counter_path else drift_bug_counter_default
    return increment_drift_bug_counter(counter_path=path, note=note)


def decision_gate(
    trace_db_path: str = "",
    baseline_path: str = "",
    drift_counter_path: str = "",
    need_rust_portfolio: bool = False,
    volume_threshold_per_day: int = 100_000,
    regression_threshold_pct: float = 30.0,
    consecutive_regressions_required: int = 2,
) -> dict[str, Any]:
    """Evaluate migration triggers and return pass/fail gate."""
    trace_db_default = _require("trace_db_default", _trace_db_default)
    baseline_snapshot_default = _require(
        "baseline_snapshot_default", _baseline_snapshot_default
    )
    drift_bug_counter_default = _require(
        "drift_bug_counter_default", _drift_bug_counter_default
    )

    tpath = Path(trace_db_path) if trace_db_path else trace_db_default
    bpath = Path(baseline_path) if baseline_path else baseline_snapshot_default
    dpath = (
        Path(drift_counter_path)
        if drift_counter_path
        else drift_bug_counter_default
    )

    drift_count = 0
    if dpath.exists():
        try:
            payload = json.loads(dpath.read_text(encoding="utf-8"))
            drift_count = int(payload.get("count", 0))
        except (ValueError, json.JSONDecodeError):
            drift_count = 0

    result = evaluate_decision_gate(
        trace_path=tpath,
        baseline_path=bpath,
        drift_bug_count=drift_count,
        need_rust_portfolio=need_rust_portfolio,
        volume_threshold_per_day=volume_threshold_per_day,
        regression_threshold_pct=regression_threshold_pct,
        consecutive_regressions_required=consecutive_regressions_required,
    )
    return {
        **result,
        "paths": {
            "trace": str(tpath),
            "baseline": str(bpath),
            "drift_counter": str(dpath),
        },
    }


def register_slo_tools(mcp: FastMCP) -> None:
    mcp.tool()(health_check)
    mcp.tool()(benchmark_calls)
    mcp.tool()(scenario_load_test)
    mcp.tool()(capture_roi_baseline)
    mcp.tool()(report_drift_bug)
    mcp.tool()(decision_gate)
