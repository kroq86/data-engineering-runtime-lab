from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mcp_generic_project_state_tools import (
    configure_generic_project_state_tools,
    project_append_event,
    project_delete_entity,
    project_export_state,
    project_get_entity,
    project_ingest_trace,
    project_list_entities,
    project_upsert_entity,
)
from trace_observability import TraceStore


class GenericProjectStateToolsTests(unittest.TestCase):
    def test_entity_crud_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configure_generic_project_state_tools(
                workspace=root,
                state_root_default=root / "state",
                trace_store_factory=lambda path=None: TraceStore(Path(path) if path else root / "traces.jsonl"),
                explain_run=lambda **kwargs: {"ok": True, "run_id": kwargs["run_id"]},
            )

            upsert = project_upsert_entity(
                entity_type="generic_entity",
                entity_id="case-1",
                payload_json='{"title":"Case 1","status":"new"}',
            )
            self.assertTrue(upsert["ok"])
            listed = project_list_entities(entity_type="generic_entity")
            self.assertEqual(listed["count"], 1)
            fetched = project_get_entity(entity_type="generic_entity", entity_id="case-1")
            self.assertEqual(fetched["entity"]["title"], "Case 1")
            deleted = project_delete_entity(entity_type="generic_entity", entity_id="case-1")
            self.assertTrue(deleted["deleted"])

    def test_append_event_and_export_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configure_generic_project_state_tools(
                workspace=root,
                state_root_default=root / "state",
                trace_store_factory=lambda path=None: TraceStore(Path(path) if path else root / "traces.jsonl"),
                explain_run=lambda **kwargs: {"ok": True, "run_id": kwargs["run_id"]},
            )
            project_upsert_entity(
                entity_type="regression_case",
                entity_id="reg-1",
                payload_json='{"input":"hello","expected":"route_a"}',
            )
            event = project_append_event(
                event_type="regression.case_added",
                entity_type="regression_case",
                entity_id="reg-1",
                payload_json='{"expected":"route_a"}',
                run_id="run-1",
            )
            self.assertTrue(event["ok"])
            exported = project_export_state()
            self.assertTrue(exported["ok"])
            self.assertIn("regression_case", exported["payload"]["entities"])
            self.assertEqual(len(exported["payload"]["events"]), 1)

    def test_ingest_trace_writes_normalized_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / "traces.jsonl"
            configure_generic_project_state_tools(
                workspace=root,
                state_root_default=root / "state",
                trace_store_factory=lambda path=None: TraceStore(Path(path) if path else trace_path),
                explain_run=lambda **kwargs: {"ok": True, "run_id": kwargs["run_id"]},
            )
            out = project_ingest_trace(
                run_id="run-1",
                tool_name="project_upsert_entity",
                status="ok",
                summary="entity upserted",
                decision_reason="test trace ingestion",
                actual_effects="one entity persisted",
            )
            self.assertTrue(out["ok"])
            rows = trace_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            payload = json.loads(rows[0])
            self.assertEqual(payload["run_id"], "run-1")
            self.assertEqual(payload["decision_reason"], "test trace ingestion")
