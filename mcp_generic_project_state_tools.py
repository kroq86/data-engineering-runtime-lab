from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - local import fallback outside MCP env
    class FastMCP:  # type: ignore[override]
        pass

TraceStoreFactory = Callable[[str | None], Any]
ExplainRunFn = Callable[..., dict[str, Any]]

DEFAULT_STATE_ROOT = Path("./tests/artifacts/mcp/project_state")
DECLARED_ENTITIES: dict[str, dict[str, Any]] = {
    "generic_entity": {
        "identity_field": "entity_id",
        "writable": True,
        "description": "Generic project-scoped entity for scenarios, fixtures, and control cases.",
    },
    "regression_case": {
        "identity_field": "entity_id",
        "writable": True,
        "description": "Scenario/control-case entity used by regression suites.",
    },
}

_workspace: Path | None = None
_state_root_default: Path = DEFAULT_STATE_ROOT
_trace_store_factory: TraceStoreFactory | None = None
_explain_run_fn: ExplainRunFn | None = None


def configure_generic_project_state_tools(
    *,
    workspace: Path,
    state_root_default: Path,
    trace_store_factory: TraceStoreFactory,
    explain_run: ExplainRunFn,
) -> None:
    global _workspace, _state_root_default, _trace_store_factory, _explain_run_fn
    _workspace = workspace
    _state_root_default = state_root_default
    _trace_store_factory = trace_store_factory
    _explain_run_fn = explain_run


def _require(name: str, value: Any) -> Any:
    if value is None:
        raise RuntimeError(f"{name} is not configured")
    return value


def declared_entities() -> dict[str, dict[str, Any]]:
    return {
        entity_type: dict(meta)
        for entity_type, meta in DECLARED_ENTITIES.items()
    }


def _state_root(root_dir: str) -> Path:
    if root_dir:
        return Path(root_dir)
    return _state_root_default


def _entity_meta(entity_type: str) -> dict[str, Any]:
    if entity_type not in DECLARED_ENTITIES:
        raise ValueError(f"entity_type '{entity_type}' is not declared in project manifest")
    return DECLARED_ENTITIES[entity_type]


def _entity_path(root: Path, entity_type: str) -> Path:
    return root / "entities" / f"{entity_type}.json"


def _events_path(root: Path) -> Path:
    return root / "events.jsonl"


def _load_entities(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _write_entities(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def project_list_entities(
    entity_type: str = "generic_entity",
    root_dir: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """List declared project entities from the generic state store."""
    _entity_meta(entity_type)
    root = _state_root(root_dir)
    path = _entity_path(root, entity_type)
    rows = _load_entities(path)
    rows.sort(key=lambda row: str(row.get("updated_at_utc", "")), reverse=True)
    return {
        "ok": True,
        "entity_type": entity_type,
        "count": len(rows[:limit]),
        "entities": rows[:limit],
        "path": str(path),
    }


def project_get_entity(
    entity_type: str = "generic_entity",
    entity_id: str = "",
    root_dir: str = "",
) -> dict[str, Any]:
    """Load one declared project entity by identity key."""
    meta = _entity_meta(entity_type)
    root = _state_root(root_dir)
    path = _entity_path(root, entity_type)
    identity_field = str(meta["identity_field"])
    rows = _load_entities(path)
    entity = next(
        (row for row in rows if str(row.get(identity_field, "")) == entity_id),
        None,
    )
    return {
        "ok": entity is not None,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity": entity,
        "path": str(path),
        "reason": "" if entity is not None else "entity not found",
    }


def project_upsert_entity(
    entity_type: str = "generic_entity",
    entity_id: str = "",
    payload_json: str = "{}",
    root_dir: str = "",
    merge: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create or update a declared entity in the generic state store."""
    meta = _entity_meta(entity_type)
    if not meta.get("writable", False):
        raise ValueError(f"entity_type '{entity_type}' is not writable")
    root = _state_root(root_dir)
    path = _entity_path(root, entity_type)
    identity_field = str(meta["identity_field"])
    payload = json.loads(payload_json)
    now = datetime.now(timezone.utc).isoformat()
    rows = _load_entities(path)
    existing = next(
        (row for row in rows if str(row.get(identity_field, "")) == entity_id),
        None,
    )
    base = dict(existing or {})
    updated = {**base, **payload} if merge else dict(payload)
    updated[identity_field] = entity_id
    updated["updated_at_utc"] = now
    if existing is None:
        updated.setdefault("created_at_utc", now)
    else:
        updated.setdefault("created_at_utc", base.get("created_at_utc", now))

    if not dry_run:
        next_rows = [
            row for row in rows if str(row.get(identity_field, "")) != entity_id
        ]
        next_rows.append(updated)
        _write_entities(path, next_rows)

    return {
        "ok": True,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity": updated,
        "path": str(path),
        "dry_run": dry_run,
        "actual_effects": (
            "entity would be upserted" if dry_run else "entity upserted"
        ),
    }


def project_delete_entity(
    entity_type: str = "generic_entity",
    entity_id: str = "",
    root_dir: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete a declared entity from the generic state store."""
    meta = _entity_meta(entity_type)
    if not meta.get("writable", False):
        raise ValueError(f"entity_type '{entity_type}' is not writable")
    root = _state_root(root_dir)
    path = _entity_path(root, entity_type)
    identity_field = str(meta["identity_field"])
    rows = _load_entities(path)
    next_rows = [
        row for row in rows if str(row.get(identity_field, "")) != entity_id
    ]
    deleted = len(next_rows) != len(rows)
    if not dry_run:
        _write_entities(path, next_rows)
    return {
        "ok": True,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "deleted": deleted,
        "path": str(path),
        "dry_run": dry_run,
        "actual_effects": (
            "entity would be deleted" if dry_run else "entity deleted"
        ),
    }


def project_append_event(
    event_type: str = "project.event",
    entity_type: str = "generic_entity",
    entity_id: str = "",
    payload_json: str = "{}",
    root_dir: str = "",
    run_id: str = "",
    decision_reason: str = "",
) -> dict[str, Any]:
    """Append a generic project event to the local event log."""
    _entity_meta(entity_type)
    root = _state_root(root_dir)
    path = _events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp_utc = datetime.now(timezone.utc).isoformat()
    payload = json.loads(payload_json)
    event = {
        "timestamp_utc": timestamp_utc,
        "run_id": run_id or f"event-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "decision_reason": decision_reason,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=True) + "\n")
    return {"ok": True, "event": event, "path": str(path)}


def project_ingest_trace(
    run_id: str,
    tool_name: str,
    status: str,
    summary: str,
    trace_db_path: str = "",
    error_text: str = "",
    scenario_id: str = "project_state",
    correlation_id: str = "",
    attempt: int = 1,
    retry_classification: str = "not_applicable",
    decision_reason: str = "",
    actual_effects: str = "",
    source_kind: str = "project_state",
    source_path: str = "",
) -> dict[str, Any]:
    """Append one normalized trace record through the generic project ingest path."""
    trace_store_factory = _require("trace_store_factory", _trace_store_factory)
    store = trace_store_factory(trace_db_path or None)
    record = store.append(
        {
            "run_id": run_id,
            "correlation_id": correlation_id or run_id,
            "tool_name": tool_name,
            "status": status,
            "summary": summary,
            "error_text": error_text,
            "attempt": int(attempt),
            "retry_classification": retry_classification,
            "decision_reason": decision_reason,
            "actual_effects": actual_effects,
            "scenario_id": scenario_id,
            "source_kind": source_kind,
            "source_path": source_path,
        }
    )
    return {"ok": True, "trace_path": str(store.path), "record": record}


def project_explain_run(
    run_id: str,
    trace_db_path: str = "",
    max_timeline_events: int = 20,
) -> dict[str, Any]:
    """Read one run explanation through the generic project explain entrypoint."""
    explain_run = _require("explain_run", _explain_run_fn)
    return explain_run(
        run_id=run_id,
        trace_db_path=trace_db_path,
        max_timeline_events=max_timeline_events,
    )


def project_export_state(
    root_dir: str = "",
    entity_type: str = "",
    output_path: str = "",
    include_events: bool = True,
) -> dict[str, Any]:
    """Export generic project state as a JSON snapshot."""
    root = _state_root(root_dir)
    export: dict[str, Any] = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "root_dir": str(root),
        "entities": {},
    }
    entity_types = [entity_type] if entity_type else list(DECLARED_ENTITIES.keys())
    for current_type in entity_types:
        _entity_meta(current_type)
        export["entities"][current_type] = _load_entities(
            _entity_path(root, current_type)
        )

    if include_events:
        events_path = _events_path(root)
        events: list[dict[str, Any]] = []
        if events_path.exists():
            for raw in events_path.read_text(encoding="utf-8").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    events.append(json.loads(raw))
                except (ValueError, json.JSONDecodeError):
                    continue
        export["events"] = events

    if output_path:
        path = Path(output_path)
    else:
        path = root / "exports" / "project_state_export.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(export, indent=2), encoding="utf-8")
    return {"ok": True, "output_path": str(path), "payload": export}


def register_generic_project_state_tools(mcp: FastMCP) -> None:
    mcp.tool()(project_list_entities)
    mcp.tool()(project_get_entity)
    mcp.tool()(project_upsert_entity)
    mcp.tool()(project_delete_entity)
    mcp.tool()(project_append_event)
    mcp.tool()(project_ingest_trace)
    mcp.tool()(project_explain_run)
    mcp.tool()(project_export_state)
