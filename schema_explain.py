"""
Schema explain: run EXPLAIN for caller-provided queries in DuckDB, write plans to artifacts.
Generic: no built-in profiles or templates; caller passes query_profiles_json and optional seed_sql_json.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schema_config import artifacts_dir, schemas_dir, state_root
from schema_ddl import run_ddl_in_duckdb

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]


def schema_explain(
    schema_entity_id: str,
    query_profiles_json: str = "{}",
    seed_sql_json: str = "[]",
    root_dir: str = "",
    artifacts_dir_arg: str = "",
) -> dict[str, Any]:
    """
    Run EXPLAIN for each profile in query_profiles_json (name -> SQL string). Optional seed_sql_json
    (list of SQL) runs before EXPLAIN. Writes explain_<name>.txt to artifacts. Generic: no built-in queries.
    """
    if not duckdb:
        return {
            "ok": False,
            "error": "duckdb not installed",
            "run_id": "",
            "plans": {},
            "artifacts_dir": "",
        }
    root = state_root(root_dir)
    artifacts = artifacts_dir(artifacts_dir_arg)
    artifacts.mkdir(parents=True, exist_ok=True)
    schemas_dir_path = schemas_dir(root)
    meta_path = schemas_dir_path / f"{schema_entity_id}.json"
    if not meta_path.exists():
        return {
            "ok": False,
            "error": f"schema not found: {schema_entity_id} (run schema_load first)",
            "run_id": "",
            "plans": {},
            "artifacts_dir": str(artifacts),
        }

    try:
        profiles = json.loads(query_profiles_json or "{}")
    except json.JSONDecodeError as e:
        return {
            "ok": False,
            "error": f"invalid query_profiles_json: {e}",
            "run_id": "",
            "plans": {},
            "artifacts_dir": str(artifacts),
        }
    try:
        seed_sql = json.loads(seed_sql_json or "[]")
    except json.JSONDecodeError as e:
        return {
            "ok": False,
            "error": f"invalid seed_sql_json: {e}",
            "run_id": "",
            "plans": {},
            "artifacts_dir": str(artifacts),
        }

    if not isinstance(profiles, dict):
        return {
            "ok": False,
            "error": "query_profiles_json must be a JSON object (name -> SQL string)",
            "run_id": "",
            "plans": {},
            "artifacts_dir": str(artifacts),
        }
    if not isinstance(seed_sql, list):
        return {
            "ok": False,
            "error": "seed_sql_json must be a JSON array of SQL strings",
            "run_id": "",
            "plans": {},
            "artifacts_dir": str(artifacts),
        }

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    ddl_duck = meta.get("ddl_duck", "")
    plans: dict[str, Any] = {}
    run_id = f"schema-explain-{int(datetime.now(timezone.utc).timestamp() * 1000)}"

    conn = duckdb.connect(":memory:")
    try:
        run_ddl_in_duckdb(conn, ddl_duck)
        for stmt in seed_sql:
            if isinstance(stmt, str) and stmt.strip():
                try:
                    conn.execute(stmt.strip())
                except Exception:
                    pass
        for name, sql in profiles.items():
            if not isinstance(sql, str) or not sql.strip():
                continue
            plan_text = ""
            exec_time_ms = 0.0
            try:
                result = conn.execute(sql.strip()).fetchall()
                if result and len(result[0]) >= 2:
                    plan_text = str(result[0][1])
                else:
                    plan_text = "\n".join(
                        " ".join(str(c) for c in row) for row in result
                    )
                for line in plan_text.splitlines():
                    if "Execution Time" in line or "execution_time" in line.lower():
                        m = re.search(r"([\d.]+)\s*ms", line)
                        if m:
                            exec_time_ms = float(m.group(1))
                        break
            except Exception as e:
                plan_text = f"Error: {e}"
            plans[name] = {"plan_text": plan_text, "execution_time_ms": exec_time_ms}
            (artifacts / f"explain_{name}.txt").write_text(
                plan_text, encoding="utf-8"
            )
    finally:
        conn.close()

    return {
        "ok": True,
        "run_id": run_id,
        "plans": plans,
        "artifacts_dir": str(artifacts),
        "schema_entity_id": schema_entity_id,
    }
