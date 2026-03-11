from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mcp_project_contract_tools import (
    configure_project_contract_tools,
    project_capabilities,
    project_capture_baseline,
    project_compare_baseline,
    project_manifest,
    project_run_regression,
)


class ProjectContractToolsTests(unittest.TestCase):
    def test_project_manifest_and_capabilities_expose_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configure_project_contract_tools(
                workspace=root,
                trace_db_default=root / "traces.jsonl",
                baseline_snapshot_default=root / "baseline.json",
                explain_regression_suite=lambda **_: {"ok": True, "traced_checks": [], "explain_demos": {}},
                capture_roi_baseline=lambda **_: {"ok": True, "output_path": str(root / "baseline.json")},
                benchmark_calls=lambda **_: {"ok": True, "insert_p95_ms": 1.0, "success_rate": 1.0},
                scenario_load_test=lambda **_: {
                    "ok": True,
                    "success_rate": 1.0,
                    "latency_ms": {"overall_p95": 1.0},
                    "per_operation_stats": {"e2e": {"p95_ms": 1.0}},
                },
                explain_run=lambda **_: {"ok": True},
            )

            manifest = project_manifest()
            capabilities = project_capabilities()

            self.assertTrue(manifest["ok"])
            self.assertIn("trace", manifest["schemas"])
            self.assertIn("project_run_regression", manifest["operations"]["regression"])
            self.assertTrue(capabilities["capabilities"]["stable_trace_schema"])
            self.assertEqual(capabilities["schemas"]["verdict"], "verdict.v1")

    def test_project_run_regression_returns_pass_with_expected_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configure_project_contract_tools(
                workspace=root,
                trace_db_default=root / "traces.jsonl",
                baseline_snapshot_default=root / "baseline.json",
                explain_regression_suite=lambda **_: {
                    "ok": True,
                    "traced_checks": [
                        {
                            "name": "health_check",
                            "result": {"ok": True},
                            "explanation": {"status": "ok", "summary": "health ok"},
                        }
                    ],
                    "explain_demos": {
                        "demo_explain_run": {
                            "expectation": "expected_success",
                            "explanation": {"status": "ok", "summary": "happy path"},
                        },
                        "demo_explain_run_failure": {
                            "expectation": "expected_failure",
                            "explanation": {"status": "error", "summary": "runtime failure as expected"},
                        },
                    },
                },
                capture_roi_baseline=lambda **_: {"ok": True, "output_path": str(root / "baseline.json")},
                benchmark_calls=lambda **_: {"ok": True, "insert_p95_ms": 1.0, "success_rate": 1.0},
                scenario_load_test=lambda **_: {
                    "ok": True,
                    "success_rate": 1.0,
                    "latency_ms": {"overall_p95": 1.0},
                    "per_operation_stats": {"e2e": {"p95_ms": 1.0}},
                },
                explain_run=lambda **_: {"ok": True},
            )

            result = project_run_regression()

            self.assertTrue(result["ok"])
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(len(result["unexpected_regressions"]), 0)
            self.assertEqual(len(result["expected_failures"]), 1)

    def test_project_compare_baseline_flags_metric_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_path = root / "baseline.json"
            baseline_path.write_text(
                json.dumps(
                    {
                        "benchmark": {"insert_p95_ms": 10.0, "success_rate": 1.0},
                        "scenario": {
                            "success_rate": 1.0,
                            "latency_ms": {"overall_p95": 20.0},
                            "per_operation_stats": {"e2e": {"p95_ms": 50.0}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            configure_project_contract_tools(
                workspace=root,
                trace_db_default=root / "traces.jsonl",
                baseline_snapshot_default=baseline_path,
                explain_regression_suite=lambda **_: {"ok": True, "traced_checks": [], "explain_demos": {}},
                capture_roi_baseline=lambda **_: {"ok": True, "output_path": str(baseline_path)},
                benchmark_calls=lambda **_: {"ok": True, "insert_p95_ms": 20.0, "success_rate": 0.9},
                scenario_load_test=lambda **_: {
                    "ok": True,
                    "success_rate": 0.8,
                    "latency_ms": {"overall_p95": 40.0},
                    "per_operation_stats": {"e2e": {"p95_ms": 80.0}},
                },
                explain_run=lambda **_: {"ok": True},
            )

            result = project_compare_baseline()

            self.assertTrue(result["ok"])
            self.assertEqual(result["verdict"], "fail")
            self.assertGreaterEqual(len(result["unexpected_regressions"]), 1)
            self.assertIn("benchmark.insert_p95_ms", result["changed_scope"])

    def test_project_capture_baseline_wraps_result_in_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "baseline.json"
            configure_project_contract_tools(
                workspace=root,
                trace_db_default=root / "traces.jsonl",
                baseline_snapshot_default=output_path,
                explain_regression_suite=lambda **_: {"ok": True, "traced_checks": [], "explain_demos": {}},
                capture_roi_baseline=lambda **_: {"ok": True, "output_path": str(output_path)},
                benchmark_calls=lambda **_: {"ok": True, "insert_p95_ms": 1.0, "success_rate": 1.0},
                scenario_load_test=lambda **_: {
                    "ok": True,
                    "success_rate": 1.0,
                    "latency_ms": {"overall_p95": 1.0},
                    "per_operation_stats": {"e2e": {"p95_ms": 1.0}},
                },
                explain_run=lambda **_: {"ok": True},
            )

            result = project_capture_baseline()

            self.assertTrue(result["ok"])
            self.assertEqual(result["verdict"], "pass")
