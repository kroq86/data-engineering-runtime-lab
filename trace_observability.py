from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_KNOWLEDGE_EXTENSIONS = {
    ".md",
    ".py",
    ".rs",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
}
DEFAULT_EXCLUDED_DIR_NAMES = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "target",
}
DEFAULT_EXCLUDED_PATH_PARTS = {
    "tests/artifacts",
}


def _parse_utc(ts: str) -> datetime | None:
    try:
        value = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", value.lower()))


def _similarity_score(query_text: str, candidate_text: str) -> float:
    q = _tokenize(query_text)
    c = _tokenize(candidate_text)
    if not q or not c:
        return 0.0
    inter = len(q.intersection(c))
    union = len(q.union(c))
    return inter / union if union else 0.0


def _infer_error_type(status: str, error_text: str) -> str:
    if status.lower() == "ok" or not error_text.strip():
        return "none"
    token = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", error_text)
    if not token:
        return "unknown_error"
    return token[0].lower()


def _normalize_trace_record(record: dict[str, Any]) -> dict[str, Any]:
    status = str(record.get("status", "ok"))
    error_text = str(record.get("error_text", ""))
    normalized: dict[str, Any] = {
        "run_id": str(record.get("run_id", "run-unknown")),
        "correlation_id": str(
            record.get("correlation_id", record.get("run_id", "run-unknown"))
        ),
        "tool_name": str(record.get("tool_name", "unknown_tool")),
        "status": status,
        "summary": str(record.get("summary", "")),
        "error_text": error_text,
        "error_type": str(
            record.get("error_type", _infer_error_type(status, error_text))
        ),
        "attempt": int(record.get("attempt", 1)),
        "retry_classification": str(
            record.get("retry_classification", "not_applicable")
        ),
        "decision_reason": str(record.get("decision_reason", "")),
        "actual_effects": str(record.get("actual_effects", "")),
        "elapsed_ms": float(record.get("elapsed_ms", 0.0)),
        "scenario_id": str(record.get("scenario_id", "adhoc")),
        "environment": str(record.get("environment", "local")),
        "source_kind": str(record.get("source_kind", "tool_trace")),
        "source_path": str(record.get("source_path", "")),
    }
    for key, value in record.items():
        if key not in normalized:
            normalized[key] = value
    return normalized


@dataclass(slots=True)
class TraceStore:
    path: Path

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            **_normalize_trace_record(record),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return payload

    def query(
        self,
        status: str | None = None,
        tool_name: str | None = None,
        scenario_id: str | None = None,
        start_time_utc: str | None = None,
        end_time_utc: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        start_dt = _parse_utc(start_time_utc) if start_time_utc else None
        end_dt = _parse_utc(end_time_utc) if end_time_utc else None

        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if status is not None and item.get("status") != status:
                    continue
                if (
                    tool_name is not None
                    and item.get("tool_name") != tool_name
                ):
                    continue
                if (
                    scenario_id is not None
                    and item.get("scenario_id") != scenario_id
                ):
                    continue

                if start_dt is not None or end_dt is not None:
                    item_dt = _parse_utc(str(item.get("timestamp_utc", "")))
                    if item_dt is None:
                        continue
                    if start_dt is not None and item_dt < start_dt:
                        continue
                    if end_dt is not None and item_dt > end_dt:
                        continue
                out.append(item)
        return out


def find_similar_incidents(
    store: TraceStore,
    query_text: str,
    top_k: int = 5,
    status: str | None = "error",
    tool_name: str | None = None,
    scenario_id: str | None = None,
    start_time_utc: str | None = None,
    end_time_utc: str | None = None,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    if top_k < 1:
        top_k = 1
    if min_score < 0.0:
        min_score = 0.0
    if min_score > 1.0:
        min_score = 1.0

    rows = store.query(
        status=status,
        tool_name=tool_name,
        scenario_id=scenario_id,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
    )
    scored: list[dict[str, Any]] = []
    for row in rows:
        summary = str(row.get("summary", ""))
        error_text = str(row.get("error_text", ""))
        text = f"{summary} {error_text}".strip()
        score = _similarity_score(query_text=query_text, candidate_text=text)
        if score >= min_score:
            scored.append({"score": round(score, 4), **row})
    scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return scored[:top_k]


def _memory_id_for_row(row: dict[str, Any]) -> str:
    memory_id = str(row.get("memory_id", "")).strip()
    if memory_id:
        return memory_id
    run_id = str(row.get("run_id", "run-unknown"))
    timestamp = str(row.get("timestamp_utc", "")).replace(":", "-")
    return f"mem-{run_id}-{timestamp}"


def upsert_memory_entry(
    store: TraceStore,
    *,
    run_id: str,
    summary: str,
    status: str = "ok",
    tool_name: str = "memory_entry",
    error_text: str = "",
    scenario_id: str = "memory",
    tags: list[str] | None = None,
    memory_id: str = "",
    metadata: dict[str, Any] | None = None,
    correlation_id: str = "",
    decision_reason: str = "",
    actual_effects: str = "",
) -> dict[str, Any]:
    record = store.append(
        {
            "run_id": run_id,
            "correlation_id": correlation_id or run_id,
            "tool_name": tool_name,
            "status": status,
            "summary": summary,
            "error_text": error_text,
            "scenario_id": scenario_id,
            "decision_reason": decision_reason,
            "actual_effects": actual_effects,
            "source_kind": "memory_entry",
            "memory_id": memory_id.strip(),
            "tags": sorted({tag.strip() for tag in (tags or []) if tag.strip()}),
            "metadata": metadata or {},
        }
    )
    if not str(record.get("memory_id", "")).strip():
        record["memory_id"] = _memory_id_for_row(record)
    return record


def search_memory_entries(
    store: TraceStore,
    *,
    query_text: str,
    top_k: int = 5,
    min_score: float = 0.0,
    status: str | None = None,
    tool_name: str | None = None,
    scenario_id: str | None = None,
    start_time_utc: str | None = None,
    end_time_utc: str | None = None,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    if top_k < 1:
        top_k = 1
    if min_score < 0.0:
        min_score = 0.0
    if min_score > 1.0:
        min_score = 1.0

    required_tags = {tag.strip() for tag in (tags or []) if tag.strip()}
    rows = store.query(
        status=status,
        tool_name=tool_name,
        scenario_id=scenario_id,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
    )
    scored: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("source_kind", "")) != "memory_entry":
            continue
        row_tags = {
            str(tag).strip()
            for tag in (row.get("tags", []) if isinstance(row.get("tags", []), list) else [])
            if str(tag).strip()
        }
        if required_tags and not required_tags.issubset(row_tags):
            continue

        summary = str(row.get("summary", ""))
        error_text = str(row.get("error_text", ""))
        decision_reason = str(row.get("decision_reason", ""))
        actual_effects = str(row.get("actual_effects", ""))
        candidate_text = (
            f"{summary}\n{error_text}\n{decision_reason}\n{actual_effects}".strip()
        )
        score = _similarity_score(query_text=query_text, candidate_text=candidate_text)
        if score < min_score:
            continue
        scored.append(
            {
                **row,
                "memory_id": _memory_id_for_row(row),
                "score": round(score, 4),
            }
        )

    scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return scored[:top_k]


def load_run_records(
    store: TraceStore,
    run_id: str,
) -> list[dict[str, Any]]:
    rows = store.query()
    matched = [row for row in rows if str(row.get("run_id", "")) == run_id]
    matched.sort(
        key=lambda row: (
            _parse_utc(str(row.get("timestamp_utc", ""))) or datetime.min.replace(
                tzinfo=timezone.utc
            ),
            str(row.get("tool_name", "")),
        )
    )
    return matched


def explain_run(
    store: TraceStore,
    run_id: str,
    max_timeline_events: int = 20,
) -> dict[str, Any]:
    rows = load_run_records(store=store, run_id=run_id)
    if not rows:
        return {"ok": False, "run_id": run_id, "reason": "run_id not found"}

    statuses = [str(row.get("status", "unknown")) for row in rows]
    failed = [row for row in rows if str(row.get("status", "")).lower() != "ok"]
    started_at = str(rows[0].get("timestamp_utc", ""))
    ended_at = str(rows[-1].get("timestamp_utc", ""))
    started_dt = _parse_utc(started_at)
    ended_dt = _parse_utc(ended_at)
    window_ms = 0.0
    if started_dt is not None and ended_dt is not None:
        window_ms = max((ended_dt - started_dt).total_seconds() * 1000, 0.0)

    total_elapsed_ms = sum(float(row.get("elapsed_ms", 0.0)) for row in rows)
    tools = [str(row.get("tool_name", "")) for row in rows]
    timeline = [
        {
            "timestamp_utc": str(row.get("timestamp_utc", "")),
            "tool_name": str(row.get("tool_name", "")),
            "status": str(row.get("status", "")),
            "summary": str(row.get("summary", "")),
            "error_text": str(row.get("error_text", "")),
            "correlation_id": str(row.get("correlation_id", "")),
            "attempt": int(row.get("attempt", 1)),
            "retry_classification": str(row.get("retry_classification", "")),
            "decision_reason": str(row.get("decision_reason", "")),
            "actual_effects": str(row.get("actual_effects", "")),
            "elapsed_ms": float(row.get("elapsed_ms", 0.0)),
        }
        for row in rows[:max_timeline_events]
    ]

    if failed:
        first_failure = failed[0]
        explanation = (
            f"Run {run_id} failed after {len(rows)} steps. "
            f"First failing tool was {first_failure.get('tool_name', 'unknown_tool')} "
            f"with error: {str(first_failure.get('error_text', '')).strip() or 'unspecified error'}."
        )
    else:
        explanation = (
            f"Run {run_id} completed {len(rows)} steps successfully. "
            f"Observed path: {', '.join(tools)}."
        )

    return {
        "ok": True,
        "run_id": run_id,
        "status": "error" if failed else "ok",
        "record_count": len(rows),
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "window_ms": round(window_ms, 2),
        "total_elapsed_ms": round(total_elapsed_ms, 2),
        "tool_path": tools,
        "status_counts": {
            "ok": sum(1 for status in statuses if status.lower() == "ok"),
            "error": sum(1 for status in statuses if status.lower() != "ok"),
        },
        "failed_tools": [
            {
                "tool_name": str(row.get("tool_name", "")),
                "error_text": str(row.get("error_text", "")),
                "summary": str(row.get("summary", "")),
                "decision_reason": str(row.get("decision_reason", "")),
                "retry_classification": str(row.get("retry_classification", "")),
                "actual_effects": str(row.get("actual_effects", "")),
            }
            for row in failed
        ],
        "timeline": timeline,
        "summary": explanation,
    }


def refresh_trace_from_path(
    store: TraceStore,
    source_path: Path,
    state_path: Path,
    scenario_id: str = "refresh",
) -> dict[str, Any]:
    if not source_path.exists():
        return {
            "ok": False,
            "reason": "source path does not exist",
            "imported": 0,
        }

    last_line = 0
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            last_line = int(state.get("last_line", 0))
        except (ValueError, json.JSONDecodeError):
            last_line = 0

    imported = 0
    with source_path.open("r", encoding="utf-8") as fh:
        for idx, raw in enumerate(fh, start=1):
            if idx <= last_line:
                continue
            line = raw.strip()
            if not line:
                continue
            store.append(
                {
                    "run_id": f"refresh-{idx}",
                    "tool_name": "refresh_path",
                    "status": "ok",
                    "summary": line,
                    "error_text": "",
                    "elapsed_ms": 0.0,
                    "scenario_id": scenario_id,
                }
            )
            imported += 1

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"last_line": idx if "idx" in locals() else last_line}),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "imported": imported,
        "last_line": idx if "idx" in locals() else last_line,
    }


def refresh_docs_from_path(
    store: TraceStore,
    source_dir: Path,
    state_path: Path,
    scenario_id: str = "knowledge",
    include_extensions: set[str] | None = None,
    exclude_dir_names: set[str] | None = None,
    exclude_path_parts: set[str] | None = None,
    max_file_bytes: int = 200_000,
) -> dict[str, Any]:
    if not source_dir.exists():
        return {
            "ok": False,
            "reason": "source dir does not exist",
            "imported_files": 0,
        }

    extensions = {
        ext if ext.startswith(".") else f".{ext}"
        for ext in (include_extensions or DEFAULT_KNOWLEDGE_EXTENSIONS)
    }
    excluded_dirs = set(exclude_dir_names or DEFAULT_EXCLUDED_DIR_NAMES)
    excluded_parts = {
        part.replace("\\", "/")
        for part in (exclude_path_parts or DEFAULT_EXCLUDED_PATH_PARTS)
    }

    known_mtime: dict[str, float] = {}
    if state_path.exists():
        try:
            known_mtime = json.loads(state_path.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError):
            known_mtime = {}

    imported = 0
    scanned = 0
    skipped_large_files = 0
    next_state: dict[str, float] = dict(known_mtime)
    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in excluded_dirs)
        rel_root = str(root_path.relative_to(source_dir)).replace("\\", "/")
        if rel_root != "." and any(part in rel_root for part in excluded_parts):
            dirs[:] = []
            continue

        for name in sorted(files):
            path = root_path / name
            rel_path = str(path.relative_to(source_dir)).replace("\\", "/")
            if any(part in rel_path for part in excluded_parts):
                continue
            if path.suffix.lower() not in extensions:
                continue

            scanned += 1
            stat = path.stat()
            if stat.st_size > max_file_bytes:
                next_state[str(path.resolve())] = float(stat.st_mtime)
                skipped_large_files += 1
                continue

            mtime = float(stat.st_mtime)
            key = str(path.resolve())
            if known_mtime.get(key) == mtime:
                next_state[key] = mtime
                continue

            content = path.read_text(
                encoding="utf-8", errors="ignore"
            ).strip()
            if not content:
                next_state[key] = mtime
                continue

            summary = (
                f"path: {rel_path}\n"
                f"language: {path.suffix.lower().lstrip('.') or 'text'}\n\n"
                f"{content[:500]}"
            )
            source_kind = (
                "knowledge_doc"
                if path.suffix.lower() == ".md"
                else "knowledge_source"
            )
            store.append(
                {
                    "run_id": f"docs-{int(mtime)}-{path.name}",
                    "tool_name": "refresh_docs",
                    "status": "ok",
                    "summary": summary,
                    "error_text": "",
                    "elapsed_ms": 0.0,
                    "scenario_id": scenario_id,
                    "source_kind": source_kind,
                    "source_path": str(path),
                }
            )
            next_state[key] = mtime
            imported += 1

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(next_state), encoding="utf-8")
    return {
        "ok": True,
        "imported_files": imported,
        "scanned_files": scanned,
        "skipped_large_files": skipped_large_files,
        "indexed_extensions": sorted(extensions),
    }
