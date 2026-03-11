from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from trace_observability import (
    TraceStore,
    explain_run,
    find_similar_incidents,
    load_run_records,
    refresh_docs_from_path,
    refresh_trace_from_path,
)


class SemanticObservabilityTests(unittest.TestCase):
    def test_trace_store_append_and_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "traces.jsonl"
            store = TraceStore(db_path)
            store.append(
                {
                    "run_id": "r1",
                    "tool_name": "insert_row",
                    "status": "ok",
                    "scenario_id": "smoke",
                    "summary": "insert succeeded",
                    "error_text": "",
                    "elapsed_ms": 10.0,
                }
            )
            store.append(
                {
                    "run_id": "r2",
                    "tool_name": "explain_customer",
                    "status": "error",
                    "scenario_id": "scenario-a",
                    "summary": "planner timeout during explain",
                    "error_text": "timeout waiting for lock",
                    "elapsed_ms": 120.0,
                }
            )

            failures = store.query(status="error")
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["run_id"], "r2")

    def test_find_similar_incidents_prefers_semantic_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "traces.jsonl"
            store = TraceStore(db_path)
            store.append(
                {
                    "run_id": "r-timeout",
                    "tool_name": "explain_customer",
                    "status": "error",
                    "scenario_id": "scenario-timeout",
                    "summary": "query timeout while waiting for lock",
                    "error_text": "timeout lock wait exceeded",
                    "elapsed_ms": 200.0,
                }
            )
            store.append(
                {
                    "run_id": "r-conflict",
                    "tool_name": "upsert_row",
                    "status": "error",
                    "scenario_id": "scenario-conflict",
                    "summary": "conflict detected during concurrent upsert",
                    "error_text": "optimistic conflict version mismatch",
                    "elapsed_ms": 50.0,
                }
            )

            results = find_similar_incidents(
                store=store,
                query_text="lock timeout on explain",
                top_k=1,
                status="error",
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["run_id"], "r-timeout")

    def test_similar_incidents_date_range_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "traces.jsonl"
            store = TraceStore(db_path)
            store.append(
                {
                    "timestamp_utc": "2025-01-01T00:00:00+00:00",
                    "run_id": "old",
                    "tool_name": "explain_customer",
                    "status": "error",
                    "scenario_id": "s1",
                    "summary": "old timeout lock",
                    "error_text": "timeout",
                    "elapsed_ms": 10.0,
                }
            )
            store.append(
                {
                    "timestamp_utc": "2026-01-01T00:00:00+00:00",
                    "run_id": "new",
                    "tool_name": "explain_customer",
                    "status": "error",
                    "scenario_id": "s1",
                    "summary": "new timeout lock",
                    "error_text": "timeout",
                    "elapsed_ms": 12.0,
                }
            )

            now = datetime.now(timezone.utc).isoformat()
            results = find_similar_incidents(
                store=store,
                query_text="timeout lock",
                top_k=5,
                status="error",
                start_time_utc=now,
            )
            self.assertEqual(results, [])

    def test_similar_incidents_min_score_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "traces.jsonl"
            store = TraceStore(db_path)
            store.append(
                {
                    "run_id": "match",
                    "tool_name": "explain_customer",
                    "status": "error",
                    "scenario_id": "s1",
                    "summary": "timeout lock wait",
                    "error_text": "lock timeout",
                    "elapsed_ms": 20.0,
                }
            )
            store.append(
                {
                    "run_id": "noise",
                    "tool_name": "upsert_row",
                    "status": "error",
                    "scenario_id": "s2",
                    "summary": "random unrelated text",
                    "error_text": "",
                    "elapsed_ms": 5.0,
                }
            )

            results = find_similar_incidents(
                store=store,
                query_text="timeout lock wait",
                top_k=5,
                status="error",
                min_score=0.5,
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["run_id"], "match")

    def test_refresh_trace_from_path_is_incremental(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.log"
            db_path = root / "traces.jsonl"
            state_path = root / "state.json"
            store = TraceStore(db_path)

            source.write_text("line1\nline2\n", encoding="utf-8")
            first = refresh_trace_from_path(
                store=store,
                source_path=source,
                state_path=state_path,
                scenario_id="refresh-test",
            )
            self.assertTrue(first["ok"])
            self.assertEqual(first["imported"], 2)

            source.write_text("line1\nline2\nline3\n", encoding="utf-8")
            second = refresh_trace_from_path(
                store=store,
                source_path=source,
                state_path=state_path,
                scenario_id="refresh-test",
            )
            self.assertTrue(second["ok"])
            self.assertEqual(second["imported"], 1)

            rows = store.query(tool_name="refresh_path")
            self.assertEqual(len(rows), 3)

    def test_trace_store_normalizes_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "traces.jsonl"
            store = TraceStore(db_path)
            rec = store.append(
                {
                    "run_id": "r-min",
                    "tool_name": "health_check",
                    "status": "ok",
                    "summary": "health ok",
                }
            )
            self.assertEqual(rec["scenario_id"], "adhoc")
            self.assertEqual(rec["error_text"], "")
            self.assertEqual(rec["error_type"], "none")
            self.assertEqual(rec["environment"], "local")
            self.assertEqual(rec["source_kind"], "tool_trace")
            self.assertEqual(rec["correlation_id"], "r-min")
            self.assertEqual(rec["attempt"], 1)
            self.assertEqual(rec["retry_classification"], "not_applicable")
            self.assertEqual(rec["decision_reason"], "")
            self.assertEqual(rec["actual_effects"], "")

    def test_load_run_records_and_explain_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "traces.jsonl"
            store = TraceStore(db_path)
            store.append(
                {
                    "run_id": "run-1",
                    "tool_name": "init_engine",
                    "status": "ok",
                    "summary": "engine initialized",
                    "elapsed_ms": 1.0,
                }
            )
            store.append(
                {
                    "run_id": "run-1",
                    "tool_name": "insert_row",
                    "status": "ok",
                    "summary": "inserted order 1",
                    "correlation_id": "corr-1",
                    "attempt": 1,
                    "decision_reason": "demo insert succeeded",
                    "actual_effects": "one row inserted",
                    "elapsed_ms": 2.5,
                }
            )
            store.append(
                {
                    "run_id": "run-2",
                    "tool_name": "insert_row",
                    "status": "error",
                    "summary": "conflict on insert",
                    "error_text": "version mismatch",
                    "elapsed_ms": 4.0,
                }
            )

            run_rows = load_run_records(store=store, run_id="run-1")
            self.assertEqual(len(run_rows), 2)
            self.assertEqual(run_rows[0]["tool_name"], "init_engine")

            explained = explain_run(store=store, run_id="run-1")
            self.assertTrue(explained["ok"])
            self.assertEqual(explained["status"], "ok")
            self.assertEqual(explained["record_count"], 2)
            self.assertEqual(explained["tool_path"], ["init_engine", "insert_row"])
            self.assertEqual(explained["timeline"][1]["correlation_id"], "corr-1")
            self.assertEqual(
                explained["timeline"][1]["decision_reason"],
                "demo insert succeeded",
            )
            self.assertEqual(
                explained["timeline"][1]["actual_effects"], "one row inserted"
            )
            self.assertIn("completed 2 steps successfully", explained["summary"])

    def test_explain_run_surfaces_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "traces.jsonl"
            store = TraceStore(db_path)
            store.append(
                {
                    "run_id": "run-error",
                    "tool_name": "run_e2e_flow",
                    "status": "error",
                    "summary": "duckdb validation failed",
                    "error_text": "duckdb wrapper unavailable",
                    "retry_classification": "non_retryable",
                    "decision_reason": "duckdb runtime unavailable",
                    "actual_effects": "validation stopped before query execution",
                    "elapsed_ms": 12.0,
                }
            )

            explained = explain_run(store=store, run_id="run-error")
            self.assertTrue(explained["ok"])
            self.assertEqual(explained["status"], "error")
            self.assertEqual(explained["failed_tools"][0]["tool_name"], "run_e2e_flow")
            self.assertEqual(
                explained["failed_tools"][0]["retry_classification"],
                "non_retryable",
            )
            self.assertEqual(
                explained["failed_tools"][0]["decision_reason"],
                "duckdb runtime unavailable",
            )
            self.assertIn("duckdb wrapper unavailable", explained["summary"])

    def test_refresh_docs_from_path_is_incremental(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs_dir = root / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            state_path = root / "docs_state.json"
            db_path = root / "traces.jsonl"
            store = TraceStore(db_path)

            (docs_dir / "runbook.md").write_text(
                "# Incident Runbook\nUse checkpoint and replay.",
                encoding="utf-8",
            )
            first = refresh_docs_from_path(
                store=store,
                source_dir=docs_dir,
                state_path=state_path,
                scenario_id="knowledge",
            )
            self.assertTrue(first["ok"])
            self.assertEqual(first["imported_files"], 1)

            second = refresh_docs_from_path(
                store=store,
                source_dir=docs_dir,
                state_path=state_path,
                scenario_id="knowledge",
            )
            self.assertTrue(second["ok"])
            self.assertEqual(second["imported_files"], 0)

            rows = store.query(tool_name="refresh_docs")
            self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
