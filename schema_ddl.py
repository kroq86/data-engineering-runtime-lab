"""
DDL normalization and DuckDB helpers. Generic; no domain-specific queries or profiles.
Uses Rust schema_tools binary when available (schema_config.schema_tools_bin).
"""
from __future__ import annotations

import re
import subprocess
from typing import Any

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]


def _ddl_to_duckdb_py(pg_ddl: str) -> str:
    """Make DuckDB-compatible DDL from PostgreSQL DDL (strip triggers/functions, normalize types)."""
    out = pg_ddl
    out = re.sub(r"--[^\n]*", "\n", out)
    out = re.sub(r"/\*.*?\*/", "", out, flags=re.DOTALL)
    out = re.sub(r"\bbegin\s*;", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\bcommit\s*;", "", out, flags=re.IGNORECASE)
    out = re.sub(r"set\s+search_path\s*=\s*\w+\s*;", "", out, flags=re.IGNORECASE)
    out = re.sub(
        r"create\s+or\s+replace\s+function\s+[^;]+;",
        "",
        out,
        flags=re.IGNORECASE | re.DOTALL,
    )
    out = re.sub(r"drop\s+trigger\s+if\s+exists\s+[^;]+;", "", out, flags=re.IGNORECASE)
    out = re.sub(r"create\s+trigger\s+[^;]+;", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\btimestamptz\b", "TIMESTAMP", out, flags=re.IGNORECASE)
    out = re.sub(r"\bbigserial\b", "BIGINT", out, flags=re.IGNORECASE)
    out = re.sub(r"\bserial\b", "INTEGER", out, flags=re.IGNORECASE)
    out = re.sub(r"\bjsonb\b", "JSON", out, flags=re.IGNORECASE)
    out = re.sub(r"\bboolean\b", "BOOLEAN", out, flags=re.IGNORECASE)
    out = re.sub(r"\bsmallint\b", "SMALLINT", out, flags=re.IGNORECASE)
    out = re.sub(r"\bdouble\s+precision\b", "DOUBLE", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+on\s+delete\s+cascade\b", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+on\s+delete\s+set\s+null\b", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+on\s+delete\s+set\s+default\b", "", out, flags=re.IGNORECASE)
    out = re.sub(
        r"(\bcreate\s+index\s+[^;]*?)\s+where\s+[^;]+(\s*;)",
        r"\1\2",
        out,
        flags=re.IGNORECASE,
    )
    return out


def ddl_to_duckdb(pg_ddl: str) -> str:
    """Make DuckDB-compatible DDL. Uses Rust schema_tools if available."""
    try:
        from schema_config import schema_tools_bin
        bin_path = schema_tools_bin()
        if bin_path is not None:
            r = subprocess.run(
                [str(bin_path), "normalize-ddl"],
                input=pg_ddl,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0 and r.stdout is not None:
                return r.stdout
    except Exception:
        pass
    return _ddl_to_duckdb_py(pg_ddl)


def extract_statements(ddl: str) -> list[str]:
    """Split DDL into single statements (CREATE TABLE, CREATE INDEX)."""
    stmts = []
    for part in re.split(r";\s*", ddl):
        part = part.strip()
        if not part:
            continue
        if re.match(r"create\s+table", part, re.IGNORECASE) or re.match(
            r"create\s+(unique\s+)?index", part, re.IGNORECASE
        ):
            stmts.append(part + ";")
    return stmts


def run_ddl_in_duckdb(conn: duckdb.DuckDBPyConnection, ddl_duck: str) -> list[str]:
    """Execute DDL statements in DuckDB; return list of warnings for failed statements."""
    warnings: list[str] = []
    for stmt in extract_statements(ddl_duck):
        try:
            conn.execute(stmt)
        except Exception as e:
            warnings.append(f"Statement skipped: {e!s}")
    return warnings


def get_tables_indexes(conn: duckdb.DuckDBPyConnection) -> tuple[list[str], list[dict[str, Any]]]:
    """Read table and index names from DuckDB connection."""
    tables: list[str] = []
    try:
        r = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        tables = [row[0] for row in r]
    except Exception:
        pass
    indexes: list[dict[str, Any]] = []
    for table in tables:
        try:
            r = conn.execute(f"PRAGMA index_list('{table}')").fetchall()
            for row in r:
                indexes.append({"name": str(row[0]) if row else "unknown", "table": table})
        except Exception:
            pass
    return tables, indexes
