"""
Schema ingestion, EXPLAIN, and evaluation. Generic: no built-in profiles or domain heuristics.
Uses existing MCP project state (project_upsert_entity, project_append_event), trace
(project_ingest_trace), and verdict.v1 shape so regression/explain tooling can consume results.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    class FastMCP:  # type: ignore[override]
        pass

from schema_config import configure_schema_tools
from schema_evaluate import schema_evaluate
from schema_explain import schema_explain
from schema_load import schema_load

try:
    from mcp_generic_project_state_tools import (
        project_append_event,
        project_ingest_trace,
        project_upsert_entity,
    )
except ImportError:
    project_upsert_entity = None  # type: ignore[assignment]
    project_append_event = None  # type: ignore[assignment]
    project_ingest_trace = None  # type: ignore[assignment]


def schema_evaluate_full(
    schema_path: str = "",
    ddl_text: str = "",
    schema_entity_id: str = "schema_entity",
    query_profiles_json: str = "{}",
    seed_sql_json: str = "[]",
    query_profile_names: str = "",
    root_dir: str = "",
    artifacts_dir: str = "",
) -> dict[str, Any]:
    """One-shot: schema_load → schema_explain (if query_profiles_json) → schema_evaluate."""
    load_result = schema_load(
        schema_path=schema_path,
        ddl_text=ddl_text,
        schema_entity_id=schema_entity_id,
        root_dir=root_dir,
    )
    if not load_result.get("ok"):
        return {
            "ok": False,
            "load_ok": False,
            "explain_run_id": "",
            "verdict": "fail",
            "severity": "high",
            "top_causes": [],
            "next_action": "Fix schema_load (path or ddl_text).",
            "report_path": "",
            "verdict_path": "",
            "error": load_result.get("error", "schema_load failed"),
        }

    if project_upsert_entity is not None:
        try:
            project_upsert_entity(
                entity_type="generic_entity",
                entity_id=schema_entity_id,
                payload_json=json.dumps(
                    {
                        "schema_entity_id": schema_entity_id,
                        "tables_count": load_result.get("tables_count", 0),
                        "indexes_count": load_result.get("indexes_count", 0),
                        "meta_path": load_result.get("meta_path", ""),
                        "source": "schema_load",
                    },
                    ensure_ascii=False,
                ),
                root_dir=root_dir,
            )
        except Exception:
            pass

    explain_result = schema_explain(
        schema_entity_id=schema_entity_id,
        query_profiles_json=query_profiles_json,
        seed_sql_json=seed_sql_json,
        root_dir=root_dir,
        artifacts_dir_arg=artifacts_dir,
    )
    if not explain_result.get("ok"):
        return {
            "ok": False,
            "load_ok": True,
            "explain_run_id": explain_result.get("run_id", ""),
            "verdict": "fail",
            "severity": "high",
            "top_causes": [],
            "next_action": "Fix schema_explain (check query_profiles_json, seed_sql_json).",
            "report_path": "",
            "verdict_path": "",
            "error": explain_result.get("error", "schema_explain failed"),
        }

    eval_result = schema_evaluate(
        schema_entity_id=schema_entity_id,
        query_profile_names=query_profile_names,
        root_dir=root_dir,
        artifacts_dir_arg=artifacts_dir or explain_result.get("artifacts_dir", ""),
    )
    if not eval_result.get("ok"):
        return {
            "ok": False,
            "load_ok": True,
            "explain_run_id": explain_result.get("run_id", ""),
            "verdict": eval_result.get("verdict", "fail"),
            "severity": eval_result.get("severity", "high"),
            "top_causes": eval_result.get("top_causes", []),
            "next_action": eval_result.get("next_action", ""),
            "report_path": eval_result.get("report_path", ""),
            "verdict_path": eval_result.get("verdict_path", ""),
            "error": eval_result.get("error", "schema_evaluate failed"),
        }

    run_id = explain_result.get("run_id", "")
    verdict = eval_result.get("verdict")
    top_causes = eval_result.get("top_causes", [])
    next_action = eval_result.get("next_action", "")

    if project_append_event is not None:
        try:
            project_append_event(
                event_type="schema.evaluation.completed",
                entity_type="generic_entity",
                entity_id=schema_entity_id,
                payload_json=json.dumps(
                    {
                        "verdict": verdict,
                        "severity": eval_result.get("severity"),
                        "top_causes": top_causes[:5],
                        "report_path": eval_result.get("report_path", ""),
                    },
                    ensure_ascii=False,
                ),
                root_dir=root_dir,
                run_id=run_id,
                decision_reason="schema_evaluate_full completed; verdict.v1 compatible",
            )
        except Exception:
            pass

    if project_ingest_trace is not None:
        try:
            project_ingest_trace(
                run_id=run_id,
                tool_name="schema_evaluate_full",
                status="error" if verdict == "warn" else "ok",
                summary=f"schema_evaluate_full {schema_entity_id}: {verdict}",
                error_text="; ".join(top_causes[:3]) if verdict == "warn" else "",
                scenario_id="schema_validation",
                source_kind="schema_tools",
                source_path=eval_result.get("report_path", ""),
                decision_reason="schema evaluation run recorded for explain_run",
            )
        except Exception:
            pass

    return {
        "ok": True,
        "load_ok": True,
        "explain_run_id": run_id,
        "verdict": verdict,
        "severity": eval_result.get("severity"),
        "unexpected_regressions": eval_result.get("unexpected_regressions", []),
        "expected_failures": eval_result.get("expected_failures", []),
        "changed_scope": eval_result.get("changed_scope", []),
        "top_causes": top_causes,
        "next_action": next_action,
        "report_path": eval_result.get("report_path", ""),
        "verdict_path": eval_result.get("verdict_path", ""),
    }


def register_schema_tools(mcp: FastMCP) -> None:
    """Register schema tools with the MCP server."""

    @mcp.tool()
    def schema_load_tool(
        schema_path: str = "",
        ddl_text: str = "",
        schema_entity_id: str = "schema_entity",
        root_dir: str = "",
    ) -> dict[str, Any]:
        """Ingest DDL from file or raw text, validate with DuckDB, store metadata in project state (schemas/)."""
        return schema_load(
            schema_path=schema_path,
            ddl_text=ddl_text,
            schema_entity_id=schema_entity_id,
            root_dir=root_dir,
        )

    @mcp.tool()
    def schema_explain_tool(
        schema_entity_id: str = "schema_entity",
        query_profiles_json: str = "{}",
        seed_sql_json: str = "[]",
        root_dir: str = "",
        artifacts_dir: str = "",
    ) -> dict[str, Any]:
        """Run EXPLAIN for each profile in query_profiles_json (JSON: name -> SQL). Optional seed_sql_json (JSON array of SQL) runs before EXPLAIN. Writes explain_<name>.txt."""
        return schema_explain(
            schema_entity_id=schema_entity_id,
            query_profiles_json=query_profiles_json,
            seed_sql_json=seed_sql_json,
            root_dir=root_dir,
            artifacts_dir_arg=artifacts_dir,
        )

    @mcp.tool()
    def schema_evaluate_tool(
        schema_entity_id: str = "schema_entity",
        query_profile_names: str = "",
        root_dir: str = "",
        artifacts_dir: str = "",
    ) -> dict[str, Any]:
        """Build verdict from schema metadata and EXPLAIN outputs; write evaluation_report.json and verdict.md. If query_profile_names empty, discovers explain_*.txt in artifacts."""
        return schema_evaluate(
            schema_entity_id=schema_entity_id,
            query_profile_names=query_profile_names,
            root_dir=root_dir,
            artifacts_dir_arg=artifacts_dir,
        )

    @mcp.tool()
    def schema_evaluate_full_tool(
        schema_path: str = "",
        ddl_text: str = "",
        schema_entity_id: str = "schema_entity",
        query_profiles_json: str = "{}",
        seed_sql_json: str = "[]",
        query_profile_names: str = "",
        root_dir: str = "",
        artifacts_dir: str = "",
    ) -> dict[str, Any]:
        """One-shot: load schema → run EXPLAIN (from query_profiles_json/seed_sql_json) → evaluate. Generic: you supply queries and optional seed SQL."""
        return schema_evaluate_full(
            schema_path=schema_path,
            ddl_text=ddl_text,
            schema_entity_id=schema_entity_id,
            query_profiles_json=query_profiles_json,
            seed_sql_json=seed_sql_json,
            query_profile_names=query_profile_names,
            root_dir=root_dir,
            artifacts_dir=artifacts_dir,
        )
