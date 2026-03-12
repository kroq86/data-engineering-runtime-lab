from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mcp_generic_project_state_tools import configure_generic_project_state_tools
from mcp_project_heuristic_tools import (
    configure_project_heuristic_tools,
    project_list_heuristics,
    project_run_heuristic,
)
from trace_observability import TraceStore


SAMPLE_EXPORT = """<!DOCTYPE html>
<html><body>
<div class="message default clearfix" id="m1">
  <div class="body">
    <div class="pull_right date details" title="01.01.2026 10:00:00 UTC+04:00">10:00</div>
    <div class="from_name">Alice</div>
    <div class="text">Продаю iPhone 13 за 1200 лари</div>
  </div>
</div>
<div class="message default clearfix" id="m2">
  <div class="body">
    <div class="pull_right date details" title="01.01.2026 10:01:00 UTC+04:00">10:01</div>
    <div class="from_name">Alice</div>
    <div class="text">Продано</div>
  </div>
</div>
<div class="message default clearfix" id="m3">
  <div class="body">
    <div class="pull_right date details" title="01.01.2026 10:02:00 UTC+04:00">10:02</div>
    <div class="from_name">Bob</div>
    <div class="text">Продаю куртку 80 лари</div>
  </div>
</div>
</body></html>
"""


class ProjectHeuristicToolsTests(unittest.TestCase):
    def test_project_list_heuristics_exposes_profiles(self) -> None:
        result = project_list_heuristics()
        self.assertTrue(result["ok"])
        self.assertIn("liquidity_signals", result["heuristics"])
        self.assertIn("price_distribution", result["heuristics"])
        self.assertIn("price_liquidity_matrix", result["heuristics"])

    def test_project_run_heuristic_persists_liquidity_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export_dir = root / "chat"
            export_dir.mkdir()
            (export_dir / "messages.html").write_text(SAMPLE_EXPORT, encoding="utf-8")

            configure_generic_project_state_tools(
                workspace=root,
                state_root_default=root / "project_state",
                trace_store_factory=lambda path=None: TraceStore(
                    path=Path(path) if path else root / "traces.jsonl"
                ),
                explain_run=lambda **_: {"ok": True},
            )
            configure_project_heuristic_tools(
                workspace=root,
                analysis_root_default=root / "heuristics",
            )

            result = project_run_heuristic(
                heuristic_name="liquidity_signals",
                source_path=str(export_dir),
                root_dir=str(root / "heuristics"),
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["heuristic_name"], "liquidity_signals")
            overall = result["result"]["overall"]
            self.assertEqual(overall["offer_count"], 2)
            self.assertEqual(overall["weak_status_offer_count"], 1)

            entities_path = root / "heuristics" / "entities" / "generic_entity.json"
            payload = json.loads(entities_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["entity_id"], "heuristic-liquidity_signals-latest")

    def test_project_run_heuristic_builds_price_liquidity_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export_dir = root / "chat"
            export_dir.mkdir()
            (export_dir / "messages.html").write_text(SAMPLE_EXPORT, encoding="utf-8")

            configure_generic_project_state_tools(
                workspace=root,
                state_root_default=root / "project_state",
                trace_store_factory=lambda path=None: TraceStore(
                    path=Path(path) if path else root / "traces.jsonl"
                ),
                explain_run=lambda **_: {"ok": True},
            )
            configure_project_heuristic_tools(
                workspace=root,
                analysis_root_default=root / "heuristics",
            )

            result = project_run_heuristic(
                heuristic_name="price_liquidity_matrix",
                source_path=str(export_dir),
                root_dir=str(root / "heuristics"),
            )

            self.assertTrue(result["ok"])
            bands = result["result"]["band_summary"]
            self.assertTrue(any(row["price_band_gel"] == "1000+" for row in bands))
            self.assertTrue(any(row["all_signal_ratio"] > 0 for row in bands))
