from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mcp_slo import capture_baseline_snapshot


class BaselineSnapshotTests(unittest.TestCase):
    def test_capture_baseline_snapshot_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "baseline.json"
            result = capture_baseline_snapshot(
                output_path=out_path,
                benchmark_result={
                    "ok": True,
                    "success_rate": 1.0,
                    "insert_p95_ms": 10.0,
                },
                scenario_result={
                    "ok": True,
                    "success_rate": 0.99,
                    "latency_ms": {"overall_p95": 22.0},
                },
                kpi_targets={
                    "troubleshooting_time_reduction_pct": 30,
                    "retrieval_p95_ms_max": 300,
                },
            )
            self.assertTrue(result["ok"])
            self.assertTrue(out_path.exists())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIn("captured_at_utc", payload)
            self.assertIn("benchmark", payload)
            self.assertIn("scenario", payload)
            self.assertIn("kpi_targets", payload)


if __name__ == "__main__":
    unittest.main()
