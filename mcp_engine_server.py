from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP
from mcp_slo import benchmark_calls_impl, scenario_load_test_impl
from trace_observability import (
    TraceStore,
    find_similar_incidents,
    refresh_trace_from_path,
)


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
TRACE_DB_DEFAULT = Path("./tests/artifacts/mcp/trace_store/traces.jsonl")
TRACE_REFRESH_STATE_DEFAULT = Path(
    "./tests/artifacts/mcp/trace_store/refresh_state.json"
)


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


def _trace_store(path: str | None = None) -> TraceStore:
    if path:
        return TraceStore(path=Path(path))
    return TraceStore(path=TRACE_DB_DEFAULT)


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
    store = _trace_store(trace_db_path or None)
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


@mcp.tool()
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
    store = _trace_store(trace_db_path or None)
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


@mcp.tool()
def refresh_trace_path(
    source_path: str,
    trace_db_path: str = "",
    refresh_state_path: str = "",
    scenario_id: str = "refresh",
) -> dict[str, Any]:
    """Incrementally ingest new lines from source path into trace store."""
    store = _trace_store(trace_db_path or None)
    state_path = (
        Path(refresh_state_path)
        if refresh_state_path
        else TRACE_REFRESH_STATE_DEFAULT
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
    out = {
        "ok": ok,
        "steps": [{name: result} for name, result in steps],
    }
    status = "ok" if ok else "error"
    summary = "health_check finished"
    error_text = "" if ok else "one or more health steps failed"
    record_tool_trace(
        run_id=f"health-{int(time.time() * 1000)}",
        tool_name="health_check",
        status=status,
        summary=summary,
        error_text=error_text,
        elapsed_ms=0.0,
        scenario_id="health",
    )
    return out


@mcp.tool()
def benchmark_calls(
    iterations: int = 5,
    root_dir: str = "./tests/artifacts/mcp/bench",
    table: str = "orders",
    min_success_rate: float = 0.99,
    max_p95_ms: float = 100.0,
) -> dict[str, Any]:
    """Benchmark MCP operations with SLO-style summary metrics."""
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
    status = "ok" if out["slo"]["passed"] else "error"
    summary = (
        f"benchmark_calls success_rate={out['success_rate']} "
        f"p95={out['insert_p95_ms']}ms"
    )
    error_text = "; ".join(out["slo"]["violations"])
    record_tool_trace(
        run_id=f"benchmark-{int(time.time() * 1000)}",
        tool_name="benchmark_calls",
        status=status,
        summary=summary,
        error_text=error_text,
        elapsed_ms=float(out["insert_avg_ms"]),
        scenario_id="benchmark",
    )
    return out


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
    status = "ok" if out["slo"]["passed"] else "error"
    summary = (
        f"scenario_load_test success_rate={out['success_rate']} "
        f"overall_p95={out['latency_ms']['overall_p95']}ms"
    )
    error_text = "; ".join(out["slo"]["violations"])
    record_tool_trace(
        run_id=f"scenario-{int(time.time() * 1000)}",
        tool_name="scenario_load_test",
        status=status,
        summary=summary,
        error_text=error_text,
        elapsed_ms=float(out["latency_ms"]["overall_p95"]),
        scenario_id="scenario",
    )
    return out


if __name__ == "__main__":
    mcp.run()
