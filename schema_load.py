"""
Schema load: ingest DDL, validate with DuckDB, store metadata in project state.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schema_config import require_workspace, schemas_dir, state_root
from schema_ddl import ddl_to_duckdb, get_tables_indexes, run_ddl_in_duckdb

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]


def schema_load(
    schema_path: str = "",
    ddl_text: str = "",
    schema_entity_id: str = "schema_entity",
    root_dir: str = "",
) -> dict[str, Any]:
    """
    Ingest DDL from a file or raw text, validate with DuckDB, store schema metadata in project state.
    Returns ok, tables_count, indexes_count, schema_entity_id, warnings.
    """
    if not duckdb:
        return {
            "ok": False,
            "error": "duckdb not installed",
            "schema_entity_id": schema_entity_id,
            "tables_count": 0,
            "indexes_count": 0,
            "warnings": ["duckdb unavailable"],
        }
    workspace = require_workspace()
    root = state_root(root_dir)
    schemas_dir_path = schemas_dir(root)
    schemas_dir_path.mkdir(parents=True, exist_ok=True)

    if ddl_text:
        raw_ddl = ddl_text
        source = "inline"
    elif schema_path:
        path = Path(schema_path)
        if not path.is_absolute():
            path = workspace / path
        if not path.exists():
            return {
                "ok": False,
                "error": f"schema file not found: {path}",
                "schema_entity_id": schema_entity_id,
                "tables_count": 0,
                "indexes_count": 0,
                "warnings": [],
            }
        raw_ddl = path.read_text(encoding="utf-8")
        source = str(path)
    else:
        return {
            "ok": False,
            "error": "provide schema_path or ddl_text",
            "schema_entity_id": schema_entity_id,
            "tables_count": 0,
            "indexes_count": 0,
            "warnings": [],
        }

    ddl_duck = ddl_to_duckdb(raw_ddl)
    warnings: list[str] = []
    conn = duckdb.connect(":memory:")
    try:
        w = run_ddl_in_duckdb(conn, ddl_duck)
        warnings.extend(w)
        tables, indexes = get_tables_indexes(conn)
    finally:
        conn.close()

    if "trigger" in raw_ddl.lower() or "function" in raw_ddl.lower():
        warnings.append("unsupported: trigger/function stripped for DuckDB")

    meta = {
        "schema_entity_id": schema_entity_id,
        "source": source,
        "ddl_raw_length": len(raw_ddl),
        "ddl_duck": ddl_duck,
        "tables": tables,
        "indexes": indexes,
        "tables_count": len(tables),
        "indexes_count": len(indexes),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
    }
    meta_path = schemas_dir_path / f"{schema_entity_id}.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "schema_entity_id": schema_entity_id,
        "tables_count": len(tables),
        "indexes_count": len(indexes),
        "warnings": warnings,
        "meta_path": str(meta_path),
    }
