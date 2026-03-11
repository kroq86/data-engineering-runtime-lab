from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable


def percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = pos - low
    return sorted_vals[low] * (1 - frac) + sorted_vals[high] * frac


def benchmark_calls_impl(
    iterations: int,
    root_dir: str,
    table: str,
    min_success_rate: float,
    max_p95_ms: float,
    init_engine: Callable[..., dict[str, Any]],
    insert_row: Callable[..., dict[str, Any]],
    reindex_project: Callable[..., dict[str, Any]],
    explain_customer: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if iterations < 1:
        iterations = 1

    init_res = init_engine(root_dir=root_dir, table=table)
    if not init_res.get("ok", False):
        return {"ok": False, "phase": "init", "result": init_res}

    samples: list[float] = []
    op_latencies: dict[str, list[float]] = defaultdict(list)
    failures = defaultdict(int)
    total_ops = 0
    success_ops = 0

    for i in range(iterations):
        result = insert_row(
            root_dir=root_dir,
            table=table,
            order_id=1000 + i,
            customer_id=4242,
            amount=10 + i,
        )
        elapsed = float(result.get("elapsed_ms", 0.0))
        samples.append(elapsed)
        op_latencies["insert"].append(elapsed)
        total_ops += 1
        if result.get("ok", False):
            success_ops += 1
        else:
            failures["insert"] += 1

    idx = reindex_project(root_dir=root_dir, table=table)
    exp = explain_customer(root_dir=root_dir, table=table, customer_id=4242)
    for op_name, result in [("reindex", idx), ("explain", exp)]:
        elapsed = float(result.get("elapsed_ms", 0.0))
        op_latencies[op_name].append(elapsed)
        total_ops += 1
        if result.get("ok", False):
            success_ops += 1
        else:
            failures[op_name] += 1

    sorted_samples = sorted(samples)
    insert_p50 = percentile(sorted_samples, 0.50)
    insert_p95 = percentile(sorted_samples, 0.95)
    success_rate = (success_ops / total_ops) if total_ops else 0.0
    violations: list[str] = []
    if success_rate < min_success_rate:
        violations.append(
            f"success_rate {success_rate:.4f} < {min_success_rate:.4f}"
        )
    if insert_p95 > max_p95_ms:
        violations.append(
            f"insert_p95 {insert_p95:.2f}ms > {max_p95_ms:.2f}ms"
        )

    return {
        "ok": True,
        "iterations": iterations,
        "total_operations": total_ops,
        "successful_operations": success_ops,
        "success_rate": round(success_rate, 4),
        "insert_avg_ms": (
            round(sum(samples) / len(samples), 2) if samples else 0.0
        ),
        "insert_min_ms": round(min(samples), 2) if samples else 0.0,
        "insert_p50_ms": round(insert_p50, 2) if samples else 0.0,
        "insert_p95_ms": round(insert_p95, 2) if samples else 0.0,
        "insert_max_ms": round(max(samples), 2) if samples else 0.0,
        "reindex_ms": idx.get("elapsed_ms", 0.0),
        "explain_ms": exp.get("elapsed_ms", 0.0),
        "failure_breakdown": dict(failures),
        "per_operation_stats": {
            op: {
                "count": len(vals),
                "avg_ms": round(sum(vals) / len(vals), 2) if vals else 0.0,
                "p50_ms": (
                    round(percentile(sorted(vals), 0.50), 2)
                    if vals
                    else 0.0
                ),
                "p95_ms": (
                    round(percentile(sorted(vals), 0.95), 2)
                    if vals
                    else 0.0
                ),
                "max_ms": round(max(vals), 2) if vals else 0.0,
            }
            for op, vals in op_latencies.items()
        },
        "slo": {
            "passed": len(violations) == 0,
            "thresholds": {
                "min_success_rate": min_success_rate,
                "max_p95_ms": max_p95_ms,
            },
            "violations": violations,
        },
    }


def scenario_load_test_impl(
    iterations: int,
    root_dir: str,
    table: str,
    min_success_rate: float,
    max_overall_p95_ms: float,
    max_e2e_p95_ms: float,
    init_engine: Callable[..., dict[str, Any]],
    insert_row: Callable[..., dict[str, Any]],
    upsert_row: Callable[..., dict[str, Any]],
    explain_customer: Callable[..., dict[str, Any]],
    reindex_project: Callable[..., dict[str, Any]],
    run_e2e_flow: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if iterations < 1:
        iterations = 1

    init_res = init_engine(root_dir=root_dir, table=table)
    if not init_res.get("ok", False):
        return {"ok": False, "phase": "init", "result": init_res}

    step_results: list[dict[str, Any]] = []
    failures = defaultdict(int)
    op_latencies: dict[str, list[float]] = defaultdict(list)

    for i in range(iterations):
        ops = [
            (
                "insert",
                insert_row(
                    root_dir=root_dir,
                    table=table,
                    order_id=10_000 + i,
                    customer_id=4242 if i % 3 == 0 else 100 + (i % 20),
                    amount=10 + (i % 50),
                ),
            ),
            (
                "upsert",
                upsert_row(
                    root_dir=root_dir,
                    table=table,
                    order_id=10_000 + (i // 2),
                    customer_id=4242,
                    amount=20 + (i % 40),
                ),
            ),
            (
                "explain",
                explain_customer(
                    root_dir=root_dir,
                    table=table,
                    customer_id=4242,
                ),
            ),
        ]

        if i % 3 == 0:
            reindex_res = reindex_project(root_dir=root_dir, table=table)
            ops.append(("reindex", reindex_res))
        if i % 5 == 0:
            ops.append(("e2e", run_e2e_flow()))

        for op_name, result in ops:
            ok = bool(result.get("ok", False))
            elapsed_ms = float(result.get("elapsed_ms", 0.0))
            op_latencies[op_name].append(elapsed_ms)
            if not ok:
                failures[op_name] += 1
            step_results.append({
                "op": op_name,
                "ok": ok,
                "elapsed_ms": elapsed_ms,
                "result": result,
            })

    total = len(step_results)
    success = sum(1 for s in step_results if s["ok"])
    success_rate = (success / total) if total else 0.0

    all_latencies = sorted(float(s["elapsed_ms"]) for s in step_results)
    p50 = percentile(all_latencies, 0.50)
    p95 = percentile(all_latencies, 0.95)

    op_stats: dict[str, Any] = {}
    for op_name, vals in op_latencies.items():
        svals = sorted(vals)
        op_stats[op_name] = {
            "count": len(vals),
            "avg_ms": round(sum(vals) / len(vals), 2) if vals else 0.0,
            "p50_ms": round(percentile(svals, 0.50), 2) if vals else 0.0,
            "p95_ms": round(percentile(svals, 0.95), 2) if vals else 0.0,
            "max_ms": round(max(vals), 2) if vals else 0.0,
        }

    violations: list[str] = []
    if success_rate < min_success_rate:
        msg = (
            f"success_rate {success_rate:.4f} < "
            f"min_success_rate {min_success_rate:.4f}"
        )
        violations.append(msg)
    if p95 > max_overall_p95_ms:
        msg = (
            f"overall_p95 {p95:.2f}ms > "
            f"max_overall_p95_ms {max_overall_p95_ms:.2f}ms"
        )
        violations.append(msg)
    if "e2e" in op_stats and op_stats["e2e"]["p95_ms"] > max_e2e_p95_ms:
        msg = (
            "e2e_p95 "
            f"{op_stats['e2e']['p95_ms']:.2f}ms > "
            f"max_e2e_p95_ms {max_e2e_p95_ms:.2f}ms"
        )
        violations.append(msg)

    return {
        "ok": True,
        "iterations": iterations,
        "total_operations": total,
        "successful_operations": success,
        "success_rate": round(success_rate, 4),
        "latency_ms": {
            "overall_p50": round(p50, 2),
            "overall_p95": round(p95, 2),
        },
        "failure_breakdown": dict(failures),
        "per_operation_stats": op_stats,
        "slo": {
            "passed": len(violations) == 0,
            "thresholds": {
                "min_success_rate": min_success_rate,
                "max_overall_p95_ms": max_overall_p95_ms,
                "max_e2e_p95_ms": max_e2e_p95_ms,
            },
            "violations": violations,
        },
    }
