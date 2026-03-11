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
from mcp_explainability import (
    configure_explainability_tools,
    demo_explain_run,
    demo_explain_idempotency_conflict,
    demo_explain_run_failure,
    demo_explain_semantic_failure,
    explain_regression_suite,
    explain_run,
    register_explainability_tools,
)
from mcp_slo_tools import (
    benchmark_calls,
    capture_roi_baseline,
    configure_slo_tools,
    decision_gate,
    health_check,
    register_slo_tools,
    report_drift_bug,
    scenario_load_test,
)
from mcp_trace_tools import (
    configure_trace_tools,
    record_tool_trace,
    refresh_docs_path,
    refresh_trace_path,
    register_trace_tools,
    similar_incidents,
)
from trace_observability import (
    TraceStore,
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


configure_explainability_tools(
    trace_store_factory=_trace_store,
    init_engine=init_engine,
    insert_row=insert_row,
    create_index=create_index,
    explain_customer=explain_customer,
    run_e2e_flow=run_e2e_flow,
    health_check=health_check,
    benchmark_calls=benchmark_calls,
    scenario_load_test=scenario_load_test,
    workspace=WORKSPACE,
)
configure_trace_tools(
    trace_store_factory=_trace_store,
    trace_refresh_state_default=TRACE_REFRESH_STATE_DEFAULT,
    docs_refresh_state_default=DOCS_REFRESH_STATE_DEFAULT,
)
configure_slo_tools(
    record_tool_trace=record_tool_trace,
    init_engine=init_engine,
    insert_row=insert_row,
    upsert_row=upsert_row,
    reindex_project=reindex_project,
    explain_customer=explain_customer,
    run_e2e_flow=run_e2e_flow,
    trace_db_default=TRACE_DB_DEFAULT,
    baseline_snapshot_default=BASELINE_SNAPSHOT_DEFAULT,
    drift_bug_counter_default=DRIFT_BUG_COUNTER_DEFAULT,
)
register_explainability_tools(mcp)
register_trace_tools(mcp)
register_slo_tools(mcp)


if __name__ == "__main__":
    mcp.run()
