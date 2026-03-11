from __future__ import annotations

import os
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP


WORKSPACE = Path(__file__).resolve().parent
TARGET_DIR = WORKSPACE / "target" / "debug"
BIN_DIR_ENV = os.getenv("MINI_DATA_ENGINE_BIN_DIR")
if BIN_DIR_ENV:
    bin_dir = Path(BIN_DIR_ENV)
    if not bin_dir.is_absolute():
        BIN_DIR = (WORKSPACE / bin_dir).resolve()
    else:
        BIN_DIR = bin_dir
else:
    BIN_DIR = TARGET_DIR
ENGINE_BIN = BIN_DIR / "engine_cli"
E2E_BIN = BIN_DIR / "e2e_flow"
mcp = FastMCP("mini-data-engine")


class CommandRunner(Protocol):
    def run(self, cmd: list[str], cwd: Path) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class SubprocessRunner:
    def run(self, cmd: list[str], cwd: Path) -> dict[str, Any]:
        started = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "command": " ".join(cmd),
            "elapsed_ms": round(elapsed_ms, 2),
        }


class EngineOps(Protocol):
    def init_engine(self, root_dir: str, table: str) -> dict[str, Any]:
        ...

    def insert_row(
        self,
        root_dir: str,
        table: str,
        order_id: int,
        customer_id: int,
        amount: int,
    ) -> dict[str, Any]:
        ...

    def upsert_row(
        self,
        root_dir: str,
        table: str,
        order_id: int,
        customer_id: int,
        amount: int,
    ) -> dict[str, Any]:
        ...

    def create_index(self, root_dir: str, table: str) -> dict[str, Any]:
        ...

    def explain_customer(
        self, root_dir: str, table: str, customer_id: int
    ) -> dict[str, Any]:
        ...

    def run_e2e_flow(self) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class EngineService:
    workspace: Path
    engine_bin: Path
    e2e_bin: Path
    runner: CommandRunner

    def _run(self, cmd: list[str]) -> dict[str, Any]:
        return self.runner.run(cmd=cmd, cwd=self.workspace)

    def _ensure_bins_built(self) -> dict[str, Any]:
        if self.engine_bin.exists() and self.e2e_bin.exists():
            return {"ok": True, "built": False}
        return self._run(["cargo", "build", "--bins"])

    def _run_engine_cli(self, args: list[str]) -> dict[str, Any]:
        build = self._ensure_bins_built()
        if not build.get("ok", False):
            return {
                "ok": False,
                "returncode": build.get("returncode", 1),
                "stdout": build.get("stdout", ""),
                "stderr": f"build failed\n{build.get('stderr', '')}",
                "command": "cargo build --bins",
                "elapsed_ms": build.get("elapsed_ms", 0.0),
            }
        return self._run([str(self.engine_bin), *args])

    def init_engine(self, root_dir: str, table: str) -> dict[str, Any]:
        return self._run_engine_cli(["init", root_dir, table])

    def insert_row(
        self,
        root_dir: str,
        table: str,
        order_id: int,
        customer_id: int,
        amount: int,
    ) -> dict[str, Any]:
        args = [
            "insert",
            root_dir,
            table,
            str(order_id),
            str(customer_id),
            str(amount),
        ]
        return self._run_engine_cli(args)

    def upsert_row(
        self,
        root_dir: str,
        table: str,
        order_id: int,
        customer_id: int,
        amount: int,
    ) -> dict[str, Any]:
        args = [
            "upsert",
            root_dir,
            table,
            str(order_id),
            str(customer_id),
            str(amount),
        ]
        return self._run_engine_cli(args)

    def create_index(self, root_dir: str, table: str) -> dict[str, Any]:
        return self._run_engine_cli(["index", root_dir, table])

    def explain_customer(
        self, root_dir: str, table: str, customer_id: int
    ) -> dict[str, Any]:
        return self._run_engine_cli(
            ["explain", root_dir, table, str(customer_id)]
        )

    def run_e2e_flow(self) -> dict[str, Any]:
        build = self._ensure_bins_built()
        if not build.get("ok", False):
            return build
        return self._run([str(self.e2e_bin)])


OPS: EngineOps = EngineService(
    workspace=WORKSPACE,
    engine_bin=ENGINE_BIN,
    e2e_bin=E2E_BIN,
    runner=SubprocessRunner(),
)


@mcp.tool()
def init_engine(
    root_dir: str = "./tests/artifacts/mcp/engine_data", table: str = "orders"
) -> dict[str, Any]:
    """Initialize persistent engine storage."""
    return OPS.init_engine(root_dir=root_dir, table=table)


@mcp.tool()
def insert_row(
    root_dir: str = "./tests/artifacts/mcp/engine_data",
    table: str = "orders",
    order_id: int = 1,
    customer_id: int = 4242,
    amount: int = 10,
) -> dict[str, Any]:
    """Insert one row into the persistent engine."""
    return OPS.insert_row(
        root_dir=root_dir,
        table=table,
        order_id=order_id,
        customer_id=customer_id,
        amount=amount,
    )


@mcp.tool()
def upsert_row(
    root_dir: str = "./tests/artifacts/mcp/engine_data",
    table: str = "orders",
    order_id: int = 1,
    customer_id: int = 4242,
    amount: int = 20,
) -> dict[str, Any]:
    """Upsert one row by order_id."""
    return OPS.upsert_row(
        root_dir=root_dir,
        table=table,
        order_id=order_id,
        customer_id=customer_id,
        amount=amount,
    )


@mcp.tool()
def create_index(
    root_dir: str = "./tests/artifacts/mcp/engine_data", table: str = "orders"
) -> dict[str, Any]:
    """Create customer index for engine table."""
    return OPS.create_index(root_dir=root_dir, table=table)


@mcp.tool()
def explain_customer(
    root_dir: str = "./tests/artifacts/mcp/engine_data",
    table: str = "orders",
    customer_id: int = 4242,
) -> dict[str, Any]:
    """Run EXPLAIN ANALYZE style output by customer filter."""
    return OPS.explain_customer(
        root_dir=root_dir, table=table, customer_id=customer_id
    )


@mcp.tool()
def reindex_project(
    root_dir: str = "./tests/artifacts/mcp/engine_data", table: str = "orders"
) -> dict[str, Any]:
    """Re-index this project dataset (engine_cli index)."""
    return create_index(root_dir=root_dir, table=table)


@mcp.tool()
def run_e2e_flow() -> dict[str, Any]:
    """Execute full MiniPG + MiniDatabricks + DuckDB end-to-end flow."""
    return OPS.run_e2e_flow()


@mcp.tool()
def health_check(
    root_dir: str = "./tests/artifacts/mcp/health", table: str = "orders"
) -> dict[str, Any]:
    """Run a quick MCP smoke flow and summarize status."""
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
    return {
        "ok": ok,
        "steps": [{name: result} for name, result in steps],
    }


@mcp.tool()
def benchmark_calls(
    iterations: int = 5,
    root_dir: str = "./tests/artifacts/mcp/bench",
    table: str = "orders",
    min_success_rate: float = 0.99,
    max_p95_ms: float = 100.0,
) -> dict[str, Any]:
    """Benchmark MCP operations with SLO-style summary metrics."""
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
    insert_p50 = _percentile(sorted_samples, 0.50)
    insert_p95 = _percentile(sorted_samples, 0.95)
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
                    round(_percentile(sorted(vals), 0.50), 2) if vals else 0.0
                ),
                "p95_ms": (
                    round(_percentile(sorted(vals), 0.95), 2) if vals else 0.0
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


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = pos - low
    return sorted_vals[low] * (1 - frac) + sorted_vals[high] * frac


@mcp.tool()
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
    p50 = _percentile(all_latencies, 0.50)
    p95 = _percentile(all_latencies, 0.95)

    op_stats: dict[str, Any] = {}
    for op_name, vals in op_latencies.items():
        svals = sorted(vals)
        op_stats[op_name] = {
            "count": len(vals),
            "avg_ms": round(sum(vals) / len(vals), 2) if vals else 0.0,
            "p50_ms": round(_percentile(svals, 0.50), 2) if vals else 0.0,
            "p95_ms": round(_percentile(svals, 0.95), 2) if vals else 0.0,
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


if __name__ == "__main__":
    mcp.run()
