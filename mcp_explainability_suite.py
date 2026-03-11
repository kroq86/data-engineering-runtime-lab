from __future__ import annotations

from pathlib import Path

from trace_observability import explain_run as explain_run_impl

from mcp_explainability_demos import (
    demo_explain_concurrency_failure_storm,
    demo_explain_idempotency_conflict,
    demo_explain_run,
    demo_explain_run_failure,
    demo_explain_semantic_failure,
)
from mcp_explainability_shared import (
    CONTEXT,
    append_explain_trace,
    command_result,
    require,
)


def explain_regression_suite(
    root_prefix: str = "./tests/artifacts/mcp/explain_suite",
    trace_db_path: str = "",
    benchmark_iterations: int = 8,
    scenario_iterations: int = 8,
) -> dict[str, object]:
    """Run regression checks and return explain output for each traced run."""
    trace_store_factory = require("trace_store_factory", CONTEXT.trace_store_factory)
    health_check = require("health_check", CONTEXT.health_check)
    benchmark_calls = require("benchmark_calls", CONTEXT.benchmark_calls)
    scenario_load_test = require("scenario_load_test", CONTEXT.scenario_load_test)
    workspace = require("workspace", CONTEXT.workspace)

    store = trace_store_factory(trace_db_path or None)
    root = Path(root_prefix)

    health = health_check(root_dir=str(root / "health"))
    bench = benchmark_calls(iterations=benchmark_iterations, root_dir=str(root / "bench"))
    scenario = scenario_load_test(iterations=scenario_iterations, root_dir=str(root / "scenario"))
    demo_ok = demo_explain_run(root_dir=str(root / "demo_ok"), trace_db_path=trace_db_path)
    demo_fail = demo_explain_run_failure(root_dir=str(root / "demo_fail"), trace_db_path=trace_db_path)
    semantic_fail = demo_explain_semantic_failure(root_dir=str(root / "semantic_fail"), trace_db_path=trace_db_path)
    idempotency_fail = demo_explain_idempotency_conflict(trace_db_path=trace_db_path)
    concurrency_storm = demo_explain_concurrency_failure_storm(root_dir=str(root / "concurrency_storm"), trace_db_path=trace_db_path)

    import time
    python_suite_run_id = f"python-suite-{int(time.time() * 1000)}"
    python_suite_result = command_result(
        ["python3", "-m", "unittest", "discover", "-s", str(workspace / "tests"), "-p", "test_*.py"],
        "python_unittest_discover",
        cwd=workspace,
    )
    append_explain_trace(
        store=store,
        run_id=python_suite_run_id,
        scenario_id="python_test_suite",
        source_path=str(workspace / "tests"),
        tool_name="python_test_suite",
        result=python_suite_result,
        decision_reason=("all Python unit tests passed" if python_suite_result.get("ok", False) else "Python unit test suite reported failures"),
        actual_effects="Python test discovery completed",
    )

    rust_suite_run_id = f"rust-suite-{int(time.time() * 1000)}"
    rust_suite_result = command_result(["cargo", "test"], "cargo_test", cwd=workspace)
    append_explain_trace(
        store=store,
        run_id=rust_suite_run_id,
        scenario_id="rust_test_suite",
        source_path=str(workspace / "tests"),
        tool_name="rust_test_suite",
        result=rust_suite_result,
        decision_reason=("all Rust tests and integration tests passed" if rust_suite_result.get("ok", False) else "Rust test suite reported failures"),
        actual_effects="cargo test completed across binaries and integration tests",
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
                "explanation": explain_run_impl(store=store, run_id=run_id) if run_id else {"ok": False, "reason": "missing trace_run_id"},
            }
        )

    return {
        "ok": True,
        "root_prefix": str(root),
        "traced_checks": traced_checks,
        "explain_demos": {
            "demo_explain_run": {"expectation": "expected_success", "explanation": demo_ok["explanation"]},
            "demo_explain_run_failure": {"expectation": "expected_failure", "explanation": demo_fail["explanation"]},
            "demo_explain_semantic_failure": {"expectation": "expected_failure", "explanation": semantic_fail["explanation"]},
            "demo_explain_idempotency_conflict": {"expectation": "expected_failure", "explanation": idempotency_fail["explanation"]},
            "demo_explain_concurrency_failure_storm": {"expectation": "expected_failure", "explanation": concurrency_storm["explanation"]},
        },
    }
