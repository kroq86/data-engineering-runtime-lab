"""
Schema evaluate: build verdict from metadata and EXPLAIN outputs; write report and verdict.md.
Generic: no domain heuristics; verdict from EXPLAIN success/failure and plan content only.
Uses Rust schema_tools parse-plan when available.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from schema_config import artifacts_dir, schemas_dir, state_root


def _parse_duckdb_plan_rust(text: str) -> tuple[float | None, str] | None:
    """Return (time_ms, plan_summary) if Rust binary succeeds; else None."""
    try:
        from schema_config import schema_tools_bin
        bin_path = schema_tools_bin()
        if bin_path is None:
            return None
        r = subprocess.run(
            [str(bin_path), "parse-plan"],
            input=text,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0 or not r.stdout:
            return None
        out = json.loads(r.stdout)
        return (out.get("time_ms"), out.get("plan_summary", "—"))
    except Exception:
        return None


def _parse_duckdb_plan(text: str) -> tuple[float | None, str]:
    """Parse DuckDB EXPLAIN text: (time_ms, plan_summary). Generic. Uses Rust if available."""
    rust_result = _parse_duckdb_plan_rust(text)
    if rust_result is not None:
        return rust_result
    time_ms: float | None = None
    m = re.search(r"Total Time:\s*([\d.]+)\s*s", text, re.IGNORECASE)
    if m:
        time_ms = float(m.group(1)) * 1000
    if time_ms is None:
        m = re.search(r"([\d.]+)\s*ms", text)
        if m:
            time_ms = float(m.group(1))
    if "Error:" in text:
        return time_ms, "Error"
    # DuckDB: operator names in plan (HASH_JOIN, TABLE_SCAN, TOP_N, etc.)
    duckdb_ops = {"HASH_JOIN", "TABLE_SCAN", "TOP_N", "ORDER_BY", "PROJECTION", "EMPTY_RESULT", "EXPLAIN_ANALYZE"}
    op_m = re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", text)
    ops = [o for o in op_m if o in duckdb_ops]
    # Prefer meaningful operators; map to short labels
    op_labels: list[str] = []
    seen = set()
    for op in ops:
        if op in seen:
            continue
        seen.add(op)
        if op == "HASH_JOIN":
            op_labels.append("Hash Join")
        elif op == "TABLE_SCAN":
            # Table name: memory.main.xxx (DuckDB in-memory)
            tbl_m = re.search(r"memory\.\w+\.(\w+)", text)
            if tbl_m:
                tbl = tbl_m.group(1)
                seq = "Sequential Scan" in text or "Sequential scan" in text
                op_labels.append(f"Table Scan {tbl}" + (" (Seq)" if seq else ""))
            else:
                op_labels.append("Table Scan")
        elif op == "TOP_N":
            op_labels.append("Top-N")
        elif op == "ORDER_BY":
            op_labels.append("Order By")
        elif op == "PROJECTION":
            continue
        elif op in ("EMPTY_RESULT", "EXPLAIN_ANALYZE"):
            continue
        else:
            op_labels.append(op.replace("_", " ").title())
    plan_summary = ", ".join(op_labels[:4]) if op_labels else "OK"
    return time_ms, plan_summary


def _parse_explain_plan(artifacts: Path, profile_names: list[str]) -> list[dict]:
    """Extract execution time (ms) and plan summary from each explain_<name>.txt. Generic."""
    rows: list[dict] = []
    for name in profile_names:
        path = artifacts / f"explain_{name}.txt"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        time_ms, plan_summary = _parse_duckdb_plan(text)
        rows.append({
            "profile": name,
            "execution_time_ms": time_ms,
            "plan_summary": plan_summary or "—",
        })
    return rows


def _write_path_assessment(meta: dict) -> tuple[str, str, list[str]]:
    """Generic write-path heuristics from schema metadata. Returns (verdict, assessment, causes)."""
    tables: list[str] = [t if isinstance(t, str) else str(t) for t in meta.get("tables", [])]
    causes: list[str] = []
    if any("timeline" in t.lower() or "feed" in t.lower() for t in tables):
        causes.append(
            "Write amplification – timeline/feed-style tables imply O(followers) writes per source row; fan-out at scale."
        )
    if any("stats" in t.lower() or "count" in t.lower() or "counter" in t.lower() for t in tables):
        causes.append(
            "Hot counters – stats/count-style tables updated on every engagement; viral rows = contention."
        )
    if not causes:
        return (
            "pass",
            "Write path not evaluated (generic mode). No timeline/stats-style tables detected.",
            [],
        )
    return (
        "warn",
        "Write path risky at scale: " + " ".join(causes),
        causes,
    )


def schema_evaluate(
    schema_entity_id: str,
    query_profile_names: str = "",
    root_dir: str = "",
    artifacts_dir_arg: str = "",
) -> dict:
    """
    Build verdict from schema metadata and EXPLAIN outputs. If query_profile_names empty,
    discovers explain_*.txt in artifacts_dir. Generic: no domain-specific causes or heuristics.
    """
    root = state_root(root_dir)
    artifacts = artifacts_dir(artifacts_dir_arg)
    artifacts.mkdir(parents=True, exist_ok=True)
    schemas_dir_path = schemas_dir(root)
    meta_path = schemas_dir_path / f"{schema_entity_id}.json"
    if not meta_path.exists():
        return {
            "ok": False,
            "error": f"schema not found: {schema_entity_id}",
            "verdict": "fail",
            "severity": "high",
            "report_path": "",
            "report_json_path": "",
        }

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    tables = meta.get("tables", [])

    if query_profile_names:
        profile_names = [p.strip() for p in query_profile_names.split(",") if p.strip()]
    else:
        profile_names = [
            f.stem.replace("explain_", "", 1)
            for f in artifacts.glob("explain_*.txt")
        ]

    evidence_read, read_verdict, top_causes, unexpected_regressions = (
        _read_verdict_and_causes(artifacts, profile_names)
    )
    read_path_table = _parse_explain_plan(artifacts, profile_names)
    write_verdict, write_assessment, write_causes = _write_path_assessment(meta)
    top_causes = top_causes + write_causes
    verdict = "warn" if (read_verdict == "warn" or write_verdict == "warn") else "pass"
    severity = "medium" if verdict == "warn" else "low"
    summary = (
        "Schema and EXPLAIN outputs look acceptable."
        if verdict == "pass"
        else "Review EXPLAIN outputs and schema; see top_causes."
    )
    # verdict.v1 shape (same as project_run_regression / project_compare_baseline)
    expected_failures: list[dict] = []
    changed_scope: list[str] = []

    read_path = {
        "verdict": read_verdict,
        "assessment": (
            "All provided query plans succeeded and use indexes where relevant."
            if read_verdict == "pass"
            else "Some plans failed or suggest full scans; review evidence."
        ),
        "evidence": evidence_read,
        "read_path_table": read_path_table,
        "regression_risk": "low" if read_verdict == "pass" else "medium",
        "bottleneck_at_scale": "Review plans and indexes for your workload.",
    }
    write_path = {
        "verdict": write_verdict,
        "assessment": write_assessment,
        "evidence": {},
        "regression_risk": "low" if write_verdict == "pass" else "medium",
        "bottleneck_at_scale": "N/A" if write_verdict == "pass" else "Consider async fan-out and counter updates at scale.",
    }
    if verdict == "pass":
        next_action = "Review schema and EXPLAIN outputs; add indexes or optimize queries as needed."
    else:
        next_action = (
            "Read path: review EXPLAIN outputs and indexes. "
            "Write path: if timeline/stats-style tables were flagged, run fan-out and counter updates asynchronously at scale; consider hybrid fan-out or KV for counters."
        )

    report = {
        "schema_id": schema_entity_id,
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "severity": severity,
        "summary": summary,
        "read_path": read_path,
        "write_path": write_path,
        "unexpected_regressions": unexpected_regressions,
        "expected_failures": expected_failures,
        "changed_scope": changed_scope,
        "top_causes": top_causes,
        "next_action": next_action,
        "lab_sources": [
            f"EXPLAIN outputs in {artifacts}",
            f"entity {schema_entity_id}",
            "memory schema-eval-run",
        ],
    }
    report_path = artifacts / "evaluation_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    verdict_path = artifacts / "verdict.md"
    verdict_path.write_text(
        _verdict_md(
            schema_entity_id, verdict, severity, read_verdict, write_verdict,
            write_assessment, top_causes, next_action, artifacts,
            read_path_table=read_path_table,
        ),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "verdict": verdict,
        "severity": severity,
        "unexpected_regressions": unexpected_regressions,
        "expected_failures": expected_failures,
        "changed_scope": changed_scope,
        "read_path": read_path,
        "write_path": write_path,
        "top_causes": top_causes,
        "next_action": next_action,
        "report_path": str(report_path),
        "report_json_path": str(report_path),
        "verdict_path": str(verdict_path),
    }


def _read_verdict_and_causes(
    artifacts: Path, profile_names: list[str]
) -> tuple[dict[str, str], str, list[str], list[dict]]:
    evidence_read: dict[str, str] = {}
    read_verdict = "pass"
    top_causes: list[str] = []
    unexpected_regressions: list[dict] = []
    for name in profile_names:
        path = artifacts / f"explain_{name}.txt"
        if not path.exists():
            if profile_names:
                top_causes.append(f"No EXPLAIN output for profile: {name}")
                unexpected_regressions.append(
                    {"profile": name, "reason": "missing explain output"}
                )
            continue
        text = path.read_text(encoding="utf-8")
        evidence_read[name] = text.strip()[:500]
        if "Error:" in text:
            read_verdict = "warn"
            top_causes.append(f"EXPLAIN failed for profile: {name}")
            unexpected_regressions.append(
                {"profile": name, "reason": "EXPLAIN failed", "detail": text[:200]}
            )
        elif "Seq Scan" in text and "Index" not in text:
            if "Bitmap Index" not in text and "Index Scan" not in text:
                read_verdict = "warn"
                top_causes.append(
                    f"Plan for {name} suggests full table scan; consider indexes."
                )
                unexpected_regressions.append(
                    {"profile": name, "reason": "full table scan in plan"}
                )
    if read_verdict == "pass" and not profile_names:
        read_verdict = "pass"
    return evidence_read, read_verdict, top_causes, unexpected_regressions


def _verdict_md(
    schema_entity_id: str,
    verdict: str,
    severity: str,
    read_verdict: str,
    write_verdict: str,
    write_assessment: str,
    top_causes: list[str],
    next_action: str,
    artifacts: Path,
    read_path_table: list[dict] | None = None,
) -> str:
    read_blurb = (
        "Query plans succeeded; index usage as expected."
        if read_verdict == "pass"
        else "Check EXPLAIN outputs for errors or full scans."
    )
    write_blurb = (
        write_assessment
        if write_verdict == "warn"
        else "Not evaluated (generic mode) or no write-path risks detected."
    )
    causes_block = "\n".join(f"1. **{c}**" for c in top_causes) if top_causes else "None."
    table_block = ""
    if read_path_table:
        table_block = "\n| Query pattern | Plan / index | Execution time |\n|---------------|---------------|----------------|\n"
        for row in read_path_table:
            t = row.get("execution_time_ms")
            time_str = f"{t:.3f} ms" if t is not None else "—"
            table_block += f"| {row.get('profile', '')} | {row.get('plan_summary', '—')} | {time_str} |\n"
        table_block = "\n## Read path (" + read_verdict + ")\n\n" + table_block.strip() + "\n\n---\n\n"
    write_section = ""
    if write_verdict == "warn":
        write_section = "\n## Write path (warn)\n\n" + write_assessment + "\n\n---\n\n"
    return f"""# {schema_entity_id} – Schema evaluation verdict

**Schema:** `{schema_entity_id}`
**Verdict:** `{verdict}` ({severity} severity)

---

## Short answer

- **Read path:** {read_blurb}
- **Write path:** {write_blurb}

---
{table_block}{write_section}## Top causes

{causes_block}

## Next action

{next_action}

---

*Generated from EXPLAIN outputs in `{artifacts}`. Stored in MCP state (entity, memory, events).*
"""
