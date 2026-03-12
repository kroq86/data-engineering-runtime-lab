from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - local import fallback outside MCP env
    class FastMCP:  # type: ignore[override]
        pass

from mcp_generic_project_state_tools import (
    project_append_event,
    project_ingest_trace,
    project_upsert_entity,
)
from mcp_project_heuristic_profiles import (
    HEURISTIC_RUNNERS,
    declared_heuristics,
    load_telegram_messages,
)


DEFAULT_ANALYSIS_ROOT = Path("./tests/artifacts/mcp/project_heuristics")


@dataclass
class ProjectHeuristicContext:
    workspace: Path | None = None
    analysis_root_default: Path = DEFAULT_ANALYSIS_ROOT


CONTEXT = ProjectHeuristicContext()


def configure_project_heuristic_tools(
    *,
    workspace: Path,
    analysis_root_default: Path,
) -> None:
    CONTEXT.workspace = workspace
    CONTEXT.analysis_root_default = analysis_root_default


def _analysis_root(root_dir: str) -> Path:
    if root_dir:
        return Path(root_dir)
    return CONTEXT.analysis_root_default


def project_list_heuristics() -> dict[str, Any]:
    """List declared heuristic profiles available for generic project analysis."""
    return {"ok": True, "heuristics": declared_heuristics()}


def project_run_heuristic(
    heuristic_name: str,
    source_path: str,
    source_kind: str = "telegram_html_export",
    root_dir: str = "",
    run_id: str = "",
    persist: bool = True,
    max_examples: int = 3,
) -> dict[str, Any]:
    """Run one declared heuristic profile over a source and persist the analysis through project state."""
    if heuristic_name not in HEURISTIC_RUNNERS:
        raise ValueError(f"heuristic_name '{heuristic_name}' is not declared")
    heuristic_meta = declared_heuristics()[heuristic_name]
    if source_kind not in heuristic_meta["supported_source_kinds"]:
        raise ValueError(
            f"source_kind '{source_kind}' is not supported by heuristic '{heuristic_name}'"
        )

    messages = load_telegram_messages(source_path)
    analysis = HEURISTIC_RUNNERS[heuristic_name](messages, max_examples=max_examples)
    current_run_id = run_id or f"heuristic-{heuristic_name}-{int(time.time() * 1000)}"
    root = _analysis_root(root_dir)
    entity_id = f"heuristic-{heuristic_name}-latest"

    project_ingest_trace(
        run_id=current_run_id,
        tool_name="project_run_heuristic",
        status="ok",
        summary=f"completed heuristic '{heuristic_name}'",
        scenario_id="project_heuristics",
        decision_reason=f"ran heuristic profile '{heuristic_name}' over '{source_kind}' source",
        actual_effects="heuristic analysis result prepared",
        source_kind=source_kind,
        source_path=source_path,
    )

    payload = {
        "heuristic_name": heuristic_name,
        "source_kind": source_kind,
        "source_path": source_path,
        "run_id": current_run_id,
        "result": analysis,
    }
    if persist:
        project_upsert_entity(
            entity_type="generic_entity",
            entity_id=entity_id,
            payload_json=json.dumps(payload, ensure_ascii=False),
            root_dir=str(root),
        )
        project_append_event(
            event_type="analysis.heuristic.completed",
            entity_type="generic_entity",
            entity_id=entity_id,
            payload_json=json.dumps(
                {
                    "heuristic_name": heuristic_name,
                    "source_kind": source_kind,
                    "message_count": analysis.get("message_count", 0),
                },
                ensure_ascii=False,
            ),
            root_dir=str(root),
            run_id=current_run_id,
            decision_reason="persist heuristic summary as generic project analysis state",
        )

    return {
        "ok": True,
        "run_id": current_run_id,
        "heuristic_name": heuristic_name,
        "source_kind": source_kind,
        "source_path": source_path,
        "entity_id": entity_id,
        "root_dir": str(root),
        "result": analysis,
    }


def register_project_heuristic_tools(mcp: FastMCP) -> None:
    mcp.tool()(project_list_heuristics)
    mcp.tool()(project_run_heuristic)
