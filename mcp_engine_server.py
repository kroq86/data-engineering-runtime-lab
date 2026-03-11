from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP
from mcp_slo import (
    benchmark_calls_impl,
    capture_baseline_snapshot,
    evaluate_decision_gate,
    increment_drift_bug_counter,
    scenario_load_test_impl,
)
from trace_observability import (
    TraceStore,
    find_similar_incidents,
    refresh_docs_from_path,
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
DOCS_REFRESH_STATE_DEFAULT = Path(
    "./tests/artifacts/mcp/trace_store/docs_refresh_state.json"
)
BASELINE_SNAPSHOT_DEFAULT = Path(
    "./tests/artifacts/mcp/baseline/latest_baseline.json"
)
DRIFT_BUG_COUNTER_DEFAULT = Path(
    "./tests/artifacts/mcp/baseline/drift_bug_counter.json"
)


class CommandRunner(Protocol):
    def run(
        self, cmd: list[str], cwd: Path, env: dict[str, str] | None = None
    ) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class SubprocessRunner:
    def run(
        self, cmd: list[str], cwd: Path, env: dict[str, str] | None = None
    ) -> dict[str, Any]:
        started = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            env=env,
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


@dataclass(slots=True)
class EngineSession:
    process: subprocess.Popen[str]
    root_dir: str
    table: str
    lock: threading.Lock


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

    def run_e2e_flow(self, root_dir: str) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class EngineService:
    workspace: Path
    engine_bin: Path
    e2e_bin: Path
    runner: CommandRunner
    exec_mode: str = "session"
    _sessions: dict[tuple[str, str], EngineSession] = field(
        init=False, default_factory=dict
    )

    def _runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        scripts_dir = str((self.workspace / "scripts").resolve())
        env["PATH"] = f"{scripts_dir}:{env.get('PATH', '')}"
        return env

    def _run(self, cmd: list[str]) -> dict[str, Any]:
        return self.runner.run(
            cmd=cmd, cwd=self.workspace, env=self._runtime_env()
        )

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

    def _stop_session(self, key: tuple[str, str]) -> None:
        session = self._sessions.pop(key, None)
        if session is None:
            return
        try:
            if session.process.stdin is not None:
                session.process.stdin.write("quit\n")
                session.process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            session.process.terminate()
            session.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            session.process.kill()
            session.process.wait(timeout=2)

    def _get_or_start_session(
        self, root_dir: str, table: str
    ) -> EngineSession | dict[str, Any]:
        key = (root_dir, table)
        existing = self._sessions.get(key)
        if existing is not None and existing.process.poll() is None:
            return existing
        self._stop_session(key)

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

        proc = subprocess.Popen(
            [str(self.engine_bin), "serve", root_dir, table],
            cwd=str(self.workspace),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        session = EngineSession(
            process=proc, root_dir=root_dir, table=table, lock=threading.Lock()
        )
        self._sessions[key] = session
        return session

    def _run_engine_session(self, root_dir: str, table: str, command: str) -> dict[str, Any]:
        session_or_error = self._get_or_start_session(root_dir=root_dir, table=table)
        if isinstance(session_or_error, dict):
            return session_or_error
        session = session_or_error

        started = time.perf_counter()
        with session.lock:
            if session.process.poll() is not None:
                self._stop_session((root_dir, table))
                return {
                    "ok": False,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "engine session exited unexpectedly",
                    "command": command,
                    "elapsed_ms": round(
                        (time.perf_counter() - started) * 1000, 2
                    ),
                }

            try:
                assert session.process.stdin is not None
                assert session.process.stdout is not None
                session.process.stdin.write(f"{command}\n")
                session.process.stdin.flush()
                line = session.process.stdout.readline()
            except (BrokenPipeError, OSError) as err:
                self._stop_session((root_dir, table))
                return {
                    "ok": False,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": f"engine session I/O failed: {err}",
                    "command": command,
                    "elapsed_ms": round(
                        (time.perf_counter() - started) * 1000, 2
                    ),
                }

        if not line:
            stderr = ""
            if session.process.stderr is not None:
                stderr = session.process.stderr.read().strip()
            self._stop_session((root_dir, table))
            return {
                "ok": False,
                "returncode": 1,
                "stdout": "",
                "stderr": f"engine session returned EOF\n{stderr}".strip(),
                "command": command,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        try:
            result = json.loads(line)
        except json.JSONDecodeError as err:
            self._stop_session((root_dir, table))
            return {
                "ok": False,
                "returncode": 1,
                "stdout": "",
                "stderr": f"invalid engine session response: {err}: {line.strip()}",
                "command": command,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    def init_engine(self, root_dir: str, table: str) -> dict[str, Any]:
        self._stop_session((root_dir, table))
        return self._run_engine_cli(["init", root_dir, table])

    def insert_row(
        self,
        root_dir: str,
        table: str,
        order_id: int,
        customer_id: int,
        amount: int,
    ) -> dict[str, Any]:
        if self.exec_mode == "legacy":
            args = [
                "insert",
                root_dir,
                table,
                str(order_id),
                str(customer_id),
                str(amount),
            ]
            return self._run_engine_cli(args)
        return self._run_engine_session(
            root_dir=root_dir,
            table=table,
            command=f"insert {order_id} {customer_id} {amount}",
        )

    def upsert_row(
        self,
        root_dir: str,
        table: str,
        order_id: int,
        customer_id: int,
        amount: int,
    ) -> dict[str, Any]:
        if self.exec_mode == "legacy":
            args = [
                "upsert",
                root_dir,
                table,
                str(order_id),
                str(customer_id),
                str(amount),
            ]
            return self._run_engine_cli(args)
        return self._run_engine_session(
            root_dir=root_dir,
            table=table,
            command=f"upsert {order_id} {customer_id} {amount}",
        )

    def create_index(self, root_dir: str, table: str) -> dict[str, Any]:
        if self.exec_mode == "legacy":
            return self._run_engine_cli(["index", root_dir, table])
        return self._run_engine_session(
            root_dir=root_dir, table=table, command="index"
        )

    def explain_customer(
        self, root_dir: str, table: str, customer_id: int
    ) -> dict[str, Any]:
        if self.exec_mode == "legacy":
            return self._run_engine_cli(
                ["explain", root_dir, table, str(customer_id)]
            )
        return self._run_engine_session(
            root_dir=root_dir,
            table=table,
            command=f"explain {customer_id}",
        )

    def run_e2e_flow(self, root_dir: str) -> dict[str, Any]:
        build = self._ensure_bins_built()
        if not build.get("ok", False):
            return build
        return self._run([str(self.e2e_bin), root_dir])


OPS: EngineOps = EngineService(
    workspace=WORKSPACE,
    engine_bin=ENGINE_BIN,
    e2e_bin=E2E_BIN,
    runner=SubprocessRunner(),
    exec_mode=os.getenv("MINI_DATA_ENGINE_EXEC_MODE", "session"),
)


def _trace_store(path: str | None = None) -> TraceStore:
    if path:
        return TraceStore(path=Path(path))
    return TraceStore(path=TRACE_DB_DEFAULT)


def _parse_csv_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


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
def run_e2e_flow(
    root_dir: str = "./tests/artifacts/e2e/data",
) -> dict[str, Any]:
    """Execute full MiniPG + MiniDatabricks + DuckDB end-to-end flow."""
    return OPS.run_e2e_flow(root_dir=root_dir)


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
def refresh_docs_path(
    source_dir: str = "./docs",
    trace_db_path: str = "",
    refresh_state_path: str = "",
    scenario_id: str = "knowledge",
    include_extensions: str = ".md,.py,.rs,.toml,.json,.yaml,.yml",
    exclude_dir_names: str = ".git,.idea,.pytest_cache,.venv,__pycache__,node_modules,target",
    exclude_path_parts: str = "tests/artifacts",
    max_file_bytes: int = 200000,
) -> dict[str, Any]:
    """Incrementally ingest project docs, code, and config files."""
    store = _trace_store(trace_db_path or None)
    state_path = (
        Path(refresh_state_path)
        if refresh_state_path
        else DOCS_REFRESH_STATE_DEFAULT
    )
    result = refresh_docs_from_path(
        store=store,
        source_dir=Path(source_dir),
        state_path=state_path,
        scenario_id=scenario_id,
        include_extensions=_parse_csv_set(include_extensions),
        exclude_dir_names=_parse_csv_set(exclude_dir_names),
        exclude_path_parts=_parse_csv_set(exclude_path_parts),
        max_file_bytes=max_file_bytes,
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


@mcp.tool()
def capture_roi_baseline(
    root_dir: str = "./tests/artifacts/mcp/baseline_runtime",
    table: str = "orders",
    benchmark_iterations: int = 5,
    scenario_iterations: int = 5,
    output_path: str = "",
) -> dict[str, Any]:
    """Capture baseline KPI snapshot for ROI Phase 0."""
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
        Path(output_path) if output_path else BASELINE_SNAPSHOT_DEFAULT
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


@mcp.tool()
def report_drift_bug(note: str = "", counter_path: str = "") -> dict[str, Any]:
    """Increment and persist split-logic drift bug counter."""
    path = Path(counter_path) if counter_path else DRIFT_BUG_COUNTER_DEFAULT
    return increment_drift_bug_counter(counter_path=path, note=note)


@mcp.tool()
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
    tpath = Path(trace_db_path) if trace_db_path else TRACE_DB_DEFAULT
    bpath = Path(baseline_path) if baseline_path else BASELINE_SNAPSHOT_DEFAULT
    dpath = (
        Path(drift_counter_path)
        if drift_counter_path
        else DRIFT_BUG_COUNTER_DEFAULT
    )

    drift_count = 0
    if dpath.exists():
        try:
            import json

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


if __name__ == "__main__":
    mcp.run()
