from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
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
    run_e2e_flow: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if iterations < 1:
        iterations = 1

    init_res = init_engine(root_dir=root_dir, table=table)
    if not init_res.get("ok", False):
        return {"ok": False, "phase": "init", "result": init_res}

    # Warm the end-to-end path once before collecting measured samples so
    # SLOs reflect steady-state runtime rather than first-run startup cost.
    warmup_root = f"{root_dir}/e2e_warmup"
    warmup_res = run_e2e_flow(root_dir=warmup_root)
    if not warmup_res.get("ok", False):
        return {"ok": False, "phase": "e2e_warmup", "result": warmup_res}

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
            ops.append((
                "e2e",
                run_e2e_flow(root_dir=f"{root_dir}/e2e_run_{i}"),
            ))

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
        "failed_steps": [
            s for s in step_results if not s["ok"]
        ],
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


def capture_baseline_snapshot(
    output_path: Path,
    benchmark_result: dict[str, Any],
    scenario_result: dict[str, Any],
    kpi_targets: dict[str, Any],
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark": benchmark_result,
        "scenario": scenario_result,
        "kpi_targets": kpi_targets,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"ok": True, "output_path": str(output_path), "payload": payload}


def increment_drift_bug_counter(
    counter_path: Path, note: str = ""
) -> dict[str, Any]:
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"count": 0, "events": []}
    if counter_path.exists():
        try:
            payload = json.loads(counter_path.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError):
            payload = {"count": 0, "events": []}
    payload["count"] = int(payload.get("count", 0)) + 1
    payload.setdefault("events", []).append(
        {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "note": note,
        }
    )
    counter_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "count": payload["count"],
        "counter_path": str(counter_path),
    }


def _extract_summary_metric(summary: str, key: str) -> float | None:
    if key == "benchmark_p95":
        pattern = r"p95=([0-9]+(?:\\.[0-9]+)?)ms"
    else:
        pattern = r"overall_p95=([0-9]+(?:\\.[0-9]+)?)ms"
    m = re.search(pattern, summary or "")
    if not m:
        return None
    return float(m.group(1))


def evaluate_decision_gate(
    trace_path: Path,
    baseline_path: Path,
    drift_bug_count: int,
    need_rust_portfolio: bool,
    volume_threshold_per_day: int = 100_000,
    regression_threshold_pct: float = 30.0,
    consecutive_regressions_required: int = 2,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if trace_path.exists():
        for line in trace_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except (ValueError, json.JSONDecodeError):
                continue

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    volume_24h = 0
    for row in rows:
        ts = row.get("timestamp_utc")
        if not isinstance(ts, str):
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt >= day_start:
            volume_24h += 1

    base_bench = None
    base_scen = None
    if baseline_path.exists():
        try:
            base = json.loads(baseline_path.read_text(encoding="utf-8"))
            base_bench = base.get("benchmark", {}).get("insert_p95_ms")
            base_scen = (
                base.get("scenario", {})
                .get("latency_ms", {})
                .get("overall_p95")
            )
        except (ValueError, json.JSONDecodeError):
            pass

    bench_samples: list[float] = []
    scen_samples: list[float] = []
    for row in rows:
        tool = row.get("tool_name", "")
        summary = str(row.get("summary", ""))
        if tool == "benchmark_calls":
            val = _extract_summary_metric(summary, "benchmark_p95")
            if val is not None:
                bench_samples.append(val)
        elif tool == "scenario_load_test":
            val = _extract_summary_metric(summary, "scenario_p95")
            if val is not None:
                scen_samples.append(val)

    def _count_consecutive_regressions(
        samples: list[float], baseline: float | None
    ) -> int:
        if baseline in (None, 0) or not samples:
            return 0
        count = 0
        for sample in reversed(samples):
            reg = ((sample - float(baseline)) / float(baseline)) * 100.0
            if reg > regression_threshold_pct:
                count += 1
            else:
                break
        return count

    bench_reg_count = _count_consecutive_regressions(bench_samples, base_bench)
    scen_reg_count = _count_consecutive_regressions(scen_samples, base_scen)
    regression_trigger = (
        bench_reg_count >= consecutive_regressions_required
        or scen_reg_count >= consecutive_regressions_required
    )

    checks = {
        "volume_trigger": volume_24h > volume_threshold_per_day,
        "regression_trigger": regression_trigger,
        "drift_bug_trigger": drift_bug_count >= 2,
        "portfolio_trigger": bool(need_rust_portfolio),
    }
    true_count = sum(1 for v in checks.values() if v)

    return {
        "ok": True,
        "checks": checks,
        "true_trigger_count": true_count,
        "migration_triggered": true_count >= 2,
        "details": {
            "volume_24h": volume_24h,
            "bench_regression_streak": bench_reg_count,
            "scenario_regression_streak": scen_reg_count,
            "drift_bug_count": drift_bug_count,
            "thresholds": {
                "volume_threshold_per_day": volume_threshold_per_day,
                "regression_threshold_pct": regression_threshold_pct,
                "consecutive_regressions_required": (
                    consecutive_regressions_required
                ),
            },
        },
    }
