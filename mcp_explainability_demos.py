from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mini_pg_like import EventLog, InsertAdapter, MiniPostgresLikeDB, WriteCore
from trace_observability import explain_run as explain_run_impl

from mcp_explainability_shared import (
    CONTEXT,
    append_explain_trace,
    command_result,
    demo_actual_effects,
    require,
    semantic_validation_result,
    trace_summary,
    write_core_result,
)


def demo_explain_run(
    root_dir: str = "./tests/artifacts/mcp/explain_demo",
    table: str = "orders",
    customer_id: int = 4242,
    trace_db_path: str = "",
) -> dict[str, object]:
    """Run a traced demo flow, then explain the run immediately."""
    trace_store_factory = require("trace_store_factory", CONTEXT.trace_store_factory)
    init_engine = require("init_engine", CONTEXT.init_engine)
    insert_row = require("insert_row", CONTEXT.insert_row)
    create_index = require("create_index", CONTEXT.create_index)
    explain_customer = require("explain_customer", CONTEXT.explain_customer)

    store = trace_store_factory(trace_db_path or None)
    import time
    run_id = f"demo-explain-{int(time.time() * 1000)}"
    scenario_id = "explain_demo"
    demo_root = Path(root_dir) / run_id
    steps = [
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
        append_explain_trace(
            store=store,
            run_id=run_id,
            scenario_id=scenario_id,
            source_path=str(demo_root),
            tool_name=tool_name,
            result=result,
            decision_reason=(
                "demo flow step completed"
                if result.get("ok", False)
                else "demo flow step failed"
            ),
            actual_effects=demo_actual_effects(tool_name),
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
) -> dict[str, object]:
    """Run a traced failing flow, then explain the failed run immediately."""
    trace_store_factory = require("trace_store_factory", CONTEXT.trace_store_factory)
    init_engine = require("init_engine", CONTEXT.init_engine)
    run_e2e_flow = require("run_e2e_flow", CONTEXT.run_e2e_flow)

    store = trace_store_factory(trace_db_path or None)
    import time
    run_id = f"demo-explain-failure-{int(time.time() * 1000)}"
    scenario_id = "explain_demo_failure"
    demo_root = Path(root_dir) / run_id
    blocked_root = demo_root / "blocked_root"
    blocked_root.parent.mkdir(parents=True, exist_ok=True)
    blocked_root.write_text("blocked path for failure demo", encoding="utf-8")

    steps = [
        ("init_engine", init_engine(root_dir=str(blocked_root), table=table)),
        ("run_e2e_flow", run_e2e_flow(root_dir=str(blocked_root))),
    ]

    for tool_name, result in steps:
        append_explain_trace(
            store=store,
            run_id=run_id,
            scenario_id=scenario_id,
            source_path=str(blocked_root),
            tool_name=tool_name,
            result=result,
            decision_reason="blocked path intentionally triggers runtime directory error",
            actual_effects=demo_actual_effects(tool_name),
            retry_classification=(
                "non_retryable" if not result.get("ok", False) else "not_applicable"
            ),
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
) -> dict[str, object]:
    """Run a traced semantic-corruption flow and explain the failed validation."""
    trace_store_factory = require("trace_store_factory", CONTEXT.trace_store_factory)
    init_engine = require("init_engine", CONTEXT.init_engine)
    insert_row = require("insert_row", CONTEXT.insert_row)

    store = trace_store_factory(trace_db_path or None)
    import time
    run_id = f"demo-explain-semantic-{int(time.time() * 1000)}"
    scenario_id = "explain_demo_semantic_failure"
    demo_root = Path(root_dir) / run_id
    steps = [
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
        ("validate_semantic_rules", semantic_validation_result(demo_root)),
    ]

    for tool_name, result in steps:
        append_explain_trace(
            store=store,
            run_id=run_id,
            scenario_id=scenario_id,
            source_path=str(demo_root),
            tool_name=tool_name,
            result=result,
            decision_reason=(
                "semantic validation failed because persisted amount was negative"
                if tool_name == "validate_semantic_rules" and not result.get("ok", False)
                else "semantic demo step completed"
            ),
            actual_effects=demo_actual_effects(tool_name),
            retry_classification=(
                "non_retryable" if not result.get("ok", False) else "not_applicable"
            ),
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
) -> dict[str, object]:
    """Run a traced idempotency-conflict flow through WriteCore."""
    trace_store_factory = require("trace_store_factory", CONTEXT.trace_store_factory)
    store = trace_store_factory(trace_db_path or None)
    import time
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
        "payload": {"table": "orders", "rows": [{"order_id": 1, "customer_id": 4242, "amount": 10}]},
    }
    conflict_command = {
        "run_id": f"{run_id}-2",
        "source": "mcp_demo",
        "scope": "demo",
        "idempotency_key": "orders-demo-key",
        "payload": {"table": "orders", "rows": [{"order_id": 1, "customer_id": 4242, "amount": 99}]},
    }
    steps = [
        ("write_core_execute", write_core_result(lambda: write_core.execute(first_command), "write_core.execute initial")),
        ("write_core_execute", write_core_result(lambda: write_core.execute(conflict_command), "write_core.execute conflicting_payload")),
    ]

    for index, (tool_name, result) in enumerate(steps, start=1):
        is_conflict = index == 2 and not result.get("ok", False)
        append_explain_trace(
            store=store,
            run_id=run_id,
            scenario_id=scenario_id,
            source_path="write_core:demo",
            tool_name=tool_name,
            result=result,
            decision_reason=(
                "idempotency key reused with different payload" if is_conflict else "write_core command accepted"
            ),
            actual_effects=demo_actual_effects(tool_name),
            retry_classification="non_retryable" if is_conflict else "not_applicable",
        )

    explanation = explain_run_impl(store=store, run_id=run_id)
    return {
        "ok": explanation.get("ok", False),
        "run_id": run_id,
        "trace_path": str(store.path),
        "steps": [{f"{name}_{idx}": result} for idx, (name, result) in enumerate(steps, start=1)],
        "explanation": explanation,
    }


def demo_explain_concurrency_failure_storm(
    root_dir: str = "./tests/artifacts/mcp/explain_demo_concurrency_storm",
    table: str = "orders",
    trace_db_path: str = "",
    workers: int = 4,
) -> dict[str, object]:
    """Run a traced concurrency conflict plus failure-storm scenario."""
    trace_store_factory = require("trace_store_factory", CONTEXT.trace_store_factory)
    init_engine = require("init_engine", CONTEXT.init_engine)
    run_e2e_flow = require("run_e2e_flow", CONTEXT.run_e2e_flow)
    workspace = require("workspace", CONTEXT.workspace)
    engine_bin = require("engine_bin", CONTEXT.engine_bin)

    store = trace_store_factory(trace_db_path or None)
    import time
    run_id = f"demo-explain-concurrency-{int(time.time() * 1000)}"
    scenario_id = "explain_demo_concurrency_failure_storm"
    demo_root = Path(root_dir) / run_id
    tx_root = demo_root / "tx_conflict"

    steps: list[tuple[str, dict[str, Any], str, str, str]] = []
    init_res = init_engine(root_dir=str(tx_root), table=table)
    steps.append(("init_engine", init_res, "concurrency harness initialized engine root", demo_actual_effects("init_engine"), "not_applicable"))

    tx_demo_result = command_result([str(engine_bin), "tx-demo", str(tx_root), table], "engine_cli tx-demo", cwd=workspace)
    tx_stdout = str(tx_demo_result.get("stdout", ""))
    tx_conflict_detected = "conflict on commit" in tx_stdout.lower()
    if tx_conflict_detected:
        tx_demo_result = {**tx_demo_result, "ok": False, "returncode": 1, "stderr": "tx-demo observed write-write conflict on commit"}
    steps.append((
        "tx_demo_conflict",
        tx_demo_result,
        "concurrent transactions contended on the same order_id" if tx_conflict_detected else "tx-demo completed without observed conflict",
        demo_actual_effects("tx_demo_conflict"),
        "non_retryable" if tx_conflict_detected else "not_applicable",
    ))

    blocked_root = demo_root / "storm_blocked_root"
    blocked_root.parent.mkdir(parents=True, exist_ok=True)
    blocked_root.write_text("blocked path for concurrency storm", encoding="utf-8")

    def worker(_: int) -> dict[str, Any]:
        return run_e2e_flow(root_dir=str(blocked_root))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        storm_results = list(executor.map(worker, range(max(1, workers))))
    failed_count = sum(1 for item in storm_results if not item.get("ok", False))
    max_elapsed = max(float(item.get("elapsed_ms", 0.0)) for item in storm_results)
    storm_error = next((str(item["stderr"]) for item in storm_results if item.get("stderr")), "")
    storm_result = {
        "ok": failed_count == 0,
        "returncode": 1 if failed_count else 0,
        "stdout": f"{failed_count}/{len(storm_results)} parallel e2e calls failed",
        "stderr": storm_error,
        "command": "parallel run_e2e_flow blocked-root storm",
        "elapsed_ms": round(max_elapsed, 2),
    }
    steps.append((
        "failure_storm",
        storm_result,
        f"parallel blocked-root storm produced {failed_count}/{len(storm_results)} failures",
        demo_actual_effects("failure_storm"),
        "non_retryable" if failed_count else "not_applicable",
    ))

    for tool_name, result, decision_reason, actual_effects, retry_classification in steps:
        append_explain_trace(
            store=store,
            run_id=run_id,
            scenario_id=scenario_id,
            source_path=str(demo_root),
            tool_name=tool_name,
            result=result,
            decision_reason=decision_reason,
            actual_effects=actual_effects,
            retry_classification=retry_classification,
        )

    explanation = explain_run_impl(store=store, run_id=run_id)
    return {
        "ok": explanation.get("ok", False),
        "run_id": run_id,
        "root_dir": str(demo_root),
        "trace_path": str(store.path),
        "storm_workers": max(1, workers),
        "steps": [{name: result} for name, result, *_ in steps],
        "explanation": explanation,
    }
