from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


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

    def _run_engine_session(
        self, root_dir: str, table: str, command: str
    ) -> dict[str, Any]:
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
            return self._run_engine_cli(
                [
                    "insert",
                    root_dir,
                    table,
                    str(order_id),
                    str(customer_id),
                    str(amount),
                ]
            )
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
            return self._run_engine_cli(
                [
                    "upsert",
                    root_dir,
                    table,
                    str(order_id),
                    str(customer_id),
                    str(amount),
                ]
            )
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
