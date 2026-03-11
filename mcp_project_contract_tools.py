from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - local import fallback outside MCP env
    class FastMCP:  # type: ignore[override]
        pass

ToolFn = Callable[..., dict[str, Any]]

from mcp_generic_project_state_tools import declared_entities


TRACE_SCHEMA_V1 = {
    "version": "trace.v1",
    "required_fields": [
        "run_id",
        "correlation_id",
        "tool_name",
        "status",
        "summary",
        "error_text",
        "error_type",
        "attempt",
        "retry_classification",
        "decision_reason",
        "actual_effects",
        "elapsed_ms",
        "scenario_id",
        "source_kind",
        "timestamp_utc",
    ],
    "status_values": ["ok", "error"],
}

EXPLAIN_SCHEMA_V1 = {
    "version": "explain.v1",
    "required_fields": [
        "run_id",
        "status",
        "record_count",
        "tool_path",
        "status_counts",
        "failed_tools",
        "timeline",
        "summary",
    ],
}

VERDICT_SCHEMA_V1 = {
    "version": "verdict.v1",
    "required_fields": [
        "verdict",
        "severity",
        "unexpected_regressions",
        "expected_failures",
        "changed_scope",
        "top_causes",
        "next_action",
    ],
    "verdict_values": ["pass", "fail", "warn"],
    "severity_values": ["info", "low", "medium", "high"],
}


@dataclass
class ProjectContractContext:
    workspace: Path | None = None
    trace_db_default: Path | None = None
    baseline_snapshot_default: Path | None = None
    explain_regression_suite: ToolFn | None = None
    capture_roi_baseline: ToolFn | None = None
    benchmark_calls: ToolFn | None = None
    scenario_load_test: ToolFn | None = None
    explain_run: ToolFn | None = None


CONTEXT = ProjectContractContext()


def configure_project_contract_tools(
    *,
    workspace: Path,
    trace_db_default: Path,
    baseline_snapshot_default: Path,
    explain_regression_suite: ToolFn,
    capture_roi_baseline: ToolFn,
    benchmark_calls: ToolFn,
    scenario_load_test: ToolFn,
    explain_run: ToolFn,
) -> None:
    CONTEXT.workspace = workspace
    CONTEXT.trace_db_default = trace_db_default
    CONTEXT.baseline_snapshot_default = baseline_snapshot_default
    CONTEXT.explain_regression_suite = explain_regression_suite
    CONTEXT.capture_roi_baseline = capture_roi_baseline
    CONTEXT.benchmark_calls = benchmark_calls
    CONTEXT.scenario_load_test = scenario_load_test
    CONTEXT.explain_run = explain_run


def _require(name: str, value: Any) -> Any:
    if value is None:
        raise RuntimeError(f"{name} is not configured")
    return value


def _build_verdict(
    *,
    verdict: str,
    severity: str,
    unexpected_regressions: list[dict[str, Any]] | None = None,
    expected_failures: list[dict[str, Any]] | None = None,
    changed_scope: list[str] | None = None,
    top_causes: list[str] | None = None,
    next_action: str = "",
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "severity": severity,
        "unexpected_regressions": unexpected_regressions or [],
        "expected_failures": expected_failures or [],
        "changed_scope": changed_scope or [],
        "top_causes": top_causes or [],
        "next_action": next_action,
    }


def _baseline_metric_pct_change(current: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0 if current <= 0 else 100.0
    return ((current - baseline) / baseline) * 100.0


def project_manifest() -> dict[str, Any]:
    """Describe project state roots, schemas, and supported regression primitives."""
    workspace = _require("workspace", CONTEXT.workspace)
    trace_db_default = _require("trace_db_default", CONTEXT.trace_db_default)
    baseline_snapshot_default = _require(
        "baseline_snapshot_default", CONTEXT.baseline_snapshot_default
    )
    return {
        "ok": True,
        "project": {
            "name": "mini-data-engine",
            "kind": "interactive_data_systems_lab",
            "workspace": str(workspace),
            "state_roots": {
                "trace_store": str(trace_db_default),
                "baseline_snapshot": str(baseline_snapshot_default),
                "artifacts_root": str(workspace / "tests" / "artifacts"),
            },
        },
        "entities": [
            "engine_table",
            "trace_record",
            "baseline_snapshot",
            "regression_run",
            *sorted(declared_entities().keys()),
        ],
        "operations": {
            "explain": ["explain_run"],
            "regression": [
                "explain_regression_suite",
                "project_run_regression",
                "project_capture_baseline",
                "project_compare_baseline",
            ],
            "project_state": [
                "project_list_entities",
                "project_get_entity",
                "project_upsert_entity",
                "project_delete_entity",
                "project_append_event",
                "project_ingest_trace",
                "project_explain_run",
                "project_export_state",
            ],
            "state": [
                "init_engine",
                "insert_row",
                "upsert_row",
                "create_index",
                "reindex_project",
                "run_e2e_flow",
            ],
        },
        "schemas": {
            "trace": TRACE_SCHEMA_V1,
            "explain": EXPLAIN_SCHEMA_V1,
            "verdict": VERDICT_SCHEMA_V1,
        },
    }


def project_capabilities() -> dict[str, Any]:
    """Return declared runtime capabilities and contract coverage."""
    trace_db_default = _require("trace_db_default", CONTEXT.trace_db_default)
    baseline_snapshot_default = _require(
        "baseline_snapshot_default", CONTEXT.baseline_snapshot_default
    )
    return {
        "ok": True,
        "project_name": "mini-data-engine",
        "capabilities": {
            "manifest": True,
            "stable_trace_schema": True,
            "stable_explain_schema": True,
            "unified_verdict_schema": True,
            "regression_primitives": {
                "run_regression": True,
                "capture_baseline": True,
                "compare_baseline": True,
            },
            "generic_project_state": {
                "list_entities": True,
                "get_entity": True,
                "upsert_entity": True,
                "delete_entity": True,
                "append_event": True,
                "ingest_trace": True,
                "export_state": True,
            },
            "explainability": {
                "explain_run": CONTEXT.explain_run is not None,
                "expected_failure_controls": True,
                "run_level_summary": True,
            },
            "declared_entities": declared_entities(),
            "baseline_paths": {
                "trace_store": str(trace_db_default),
                "baseline_snapshot": str(baseline_snapshot_default),
            },
        },
        "schemas": {
            "trace": TRACE_SCHEMA_V1["version"],
            "explain": EXPLAIN_SCHEMA_V1["version"],
            "verdict": VERDICT_SCHEMA_V1["version"],
        },
    }


def project_run_regression(
    root_prefix: str = "./tests/artifacts/mcp/project_regression",
    trace_db_path: str = "",
    benchmark_iterations: int = 8,
    scenario_iterations: int = 8,
) -> dict[str, Any]:
    """Run the explain-first regression bundle and return a unified verdict."""
    explain_regression_suite = _require(
        "explain_regression_suite", CONTEXT.explain_regression_suite
    )
    suite = explain_regression_suite(
        root_prefix=root_prefix,
        trace_db_path=trace_db_path,
        benchmark_iterations=benchmark_iterations,
        scenario_iterations=scenario_iterations,
    )

    unexpected_regressions: list[dict[str, Any]] = []
    expected_failures: list[dict[str, Any]] = []
    changed_scope: list[str] = []
    top_causes: list[str] = []

    for item in suite.get("traced_checks", []):
        name = str(item.get("name", "unknown_check"))
        explanation = item.get("explanation", {})
        status = str(explanation.get("status", "error"))
        if status != "ok":
            changed_scope.append(name)
            summary = str(explanation.get("summary", "unexpected traced check failure"))
            unexpected_regressions.append({"name": name, "summary": summary})
            top_causes.append(summary)

    for name, payload in suite.get("explain_demos", {}).items():
        expectation = str(payload.get("expectation", "expected_success"))
        explanation = payload.get("explanation", {})
        status = str(explanation.get("status", "error"))
        summary = str(explanation.get("summary", ""))
        if expectation == "expected_failure":
            if status == "error":
                expected_failures.append({"name": name, "summary": summary})
            else:
                changed_scope.append(name)
                unexpected_regressions.append(
                    {
                        "name": name,
                        "summary": "negative control unexpectedly passed",
                    }
                )
                top_causes.append(
                    f"{name} unexpectedly passed despite expected_failure control"
                )
        elif status != "ok":
            changed_scope.append(name)
            unexpected_regressions.append({"name": name, "summary": summary})
            top_causes.append(summary)

    verdict = "fail" if unexpected_regressions else "pass"
    severity = "high" if unexpected_regressions else "info"
    next_action = (
        "Inspect unexpected_regressions and rerun explain_run on the failing run_id values."
        if unexpected_regressions
        else "No unexpected regressions detected; keep current baseline or capture a new one if behavior changed intentionally."
    )
    return {
        "ok": True,
        "suite": suite,
        "schema_versions": {
            "trace": TRACE_SCHEMA_V1["version"],
            "explain": EXPLAIN_SCHEMA_V1["version"],
            "verdict": VERDICT_SCHEMA_V1["version"],
        },
        **_build_verdict(
            verdict=verdict,
            severity=severity,
            unexpected_regressions=unexpected_regressions,
            expected_failures=expected_failures,
            changed_scope=sorted(set(changed_scope)),
            top_causes=top_causes[:5],
            next_action=next_action,
        ),
    }


def project_capture_baseline(
    root_dir: str = "./tests/artifacts/mcp/baseline_runtime",
    table: str = "orders",
    benchmark_iterations: int = 5,
    scenario_iterations: int = 5,
    output_path: str = "",
) -> dict[str, Any]:
    """Capture a baseline snapshot and return a unified verdict envelope."""
    capture_roi_baseline = _require(
        "capture_roi_baseline", CONTEXT.capture_roi_baseline
    )
    result = capture_roi_baseline(
        root_dir=root_dir,
        table=table,
        benchmark_iterations=benchmark_iterations,
        scenario_iterations=scenario_iterations,
        output_path=output_path,
    )
    verdict = "pass" if result.get("ok", False) else "fail"
    severity = "info" if result.get("ok", False) else "high"
    baseline_path = str(result.get("output_path", output_path))
    return {
        "ok": True,
        "result": result,
        **_build_verdict(
            verdict=verdict,
            severity=severity,
            changed_scope=[baseline_path] if baseline_path else [],
            top_causes=[] if result.get("ok", False) else ["baseline capture failed"],
            next_action=(
                "Use project_compare_baseline against this snapshot after runtime or rule changes."
                if result.get("ok", False)
                else "Inspect the baseline capture failure and retry the snapshot run."
            ),
        ),
    }


def project_compare_baseline(
    baseline_path: str = "",
    root_dir: str = "./tests/artifacts/mcp/baseline_candidate",
    table: str = "orders",
    benchmark_iterations: int = 5,
    scenario_iterations: int = 5,
    benchmark_regression_pct: float = 30.0,
    scenario_regression_pct: float = 30.0,
    e2e_regression_pct: float = 30.0,
) -> dict[str, Any]:
    """Compare current benchmark/scenario results against a stored baseline."""
    baseline_snapshot_default = _require(
        "baseline_snapshot_default", CONTEXT.baseline_snapshot_default
    )
    benchmark_calls = _require("benchmark_calls", CONTEXT.benchmark_calls)
    scenario_load_test = _require(
        "scenario_load_test", CONTEXT.scenario_load_test
    )

    target_path = Path(baseline_path) if baseline_path else baseline_snapshot_default
    if not target_path.exists():
        return {
            "ok": False,
            **_build_verdict(
                verdict="fail",
                severity="high",
                unexpected_regressions=[
                    {
                        "name": "missing_baseline",
                        "summary": f"baseline snapshot not found at {target_path}",
                    }
                ],
                changed_scope=[str(target_path)],
                top_causes=[f"baseline snapshot not found at {target_path}"],
                next_action="Capture a baseline first with project_capture_baseline.",
            ),
        }

    payload = json.loads(target_path.read_text(encoding="utf-8"))
    benchmark_baseline = payload.get("benchmark", {})
    scenario_baseline = payload.get("scenario", {})

    current_benchmark = benchmark_calls(
        iterations=benchmark_iterations,
        root_dir=f"{root_dir}/bench",
        table=table,
        min_success_rate=0.0,
        max_p95_ms=1_000_000.0,
    )
    current_scenario = scenario_load_test(
        iterations=scenario_iterations,
        root_dir=f"{root_dir}/scenario",
        table=table,
        min_success_rate=0.0,
        max_overall_p95_ms=1_000_000.0,
        max_e2e_p95_ms=1_000_000.0,
    )

    unexpected_regressions: list[dict[str, Any]] = []
    changed_scope: list[str] = []
    top_causes: list[str] = []

    comparisons = [
        (
            "benchmark.insert_p95_ms",
            float(current_benchmark.get("insert_p95_ms", 0.0)),
            float(benchmark_baseline.get("insert_p95_ms", 0.0)),
            benchmark_regression_pct,
        ),
        (
            "scenario.overall_p95_ms",
            float(current_scenario.get("latency_ms", {}).get("overall_p95", 0.0)),
            float(scenario_baseline.get("latency_ms", {}).get("overall_p95", 0.0)),
            scenario_regression_pct,
        ),
        (
            "scenario.e2e_p95_ms",
            float(
                current_scenario.get("per_operation_stats", {})
                .get("e2e", {})
                .get("p95_ms", 0.0)
            ),
            float(
                scenario_baseline.get("per_operation_stats", {})
                .get("e2e", {})
                .get("p95_ms", 0.0)
            ),
            e2e_regression_pct,
        ),
    ]

    for metric_name, current_value, baseline_value, threshold_pct in comparisons:
        pct_change = _baseline_metric_pct_change(current_value, baseline_value)
        if pct_change > threshold_pct:
            changed_scope.append(metric_name)
            summary = (
                f"{metric_name} regressed by {pct_change:.2f}% "
                f"({current_value:.2f} vs baseline {baseline_value:.2f})"
            )
            unexpected_regressions.append(
                {"name": metric_name, "summary": summary}
            )
            top_causes.append(summary)

    for name, current_value, baseline_value in [
        (
            "benchmark.success_rate",
            float(current_benchmark.get("success_rate", 0.0)),
            float(benchmark_baseline.get("success_rate", 0.0)),
        ),
        (
            "scenario.success_rate",
            float(current_scenario.get("success_rate", 0.0)),
            float(scenario_baseline.get("success_rate", 0.0)),
        ),
    ]:
        if current_value < baseline_value:
            changed_scope.append(name)
            summary = (
                f"{name} dropped from baseline {baseline_value:.4f} to {current_value:.4f}"
            )
            unexpected_regressions.append({"name": name, "summary": summary})
            top_causes.append(summary)

    verdict = "fail" if unexpected_regressions else "pass"
    severity = "high" if unexpected_regressions else "info"
    return {
        "ok": True,
        "baseline_path": str(target_path),
        "baseline": payload,
        "candidate": {
            "benchmark": current_benchmark,
            "scenario": current_scenario,
        },
        **_build_verdict(
            verdict=verdict,
            severity=severity,
            unexpected_regressions=unexpected_regressions,
            changed_scope=sorted(set(changed_scope)),
            top_causes=top_causes[:5],
            next_action=(
                "Inspect candidate metrics and explain traces before updating the baseline."
                if unexpected_regressions
                else "Candidate stays within baseline thresholds; baseline can remain unchanged or be refreshed intentionally."
            ),
        ),
    }


def register_project_contract_tools(mcp: FastMCP) -> None:
    mcp.tool()(project_manifest)
    mcp.tool()(project_capabilities)
    mcp.tool()(project_run_regression)
    mcp.tool()(project_capture_baseline)
    mcp.tool()(project_compare_baseline)
