from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp_slo import (
    evaluate_decision_gate,
    increment_drift_bug_counter,
)


class DecisionGateTests(unittest.TestCase):
    def test_decision_gate_not_triggered_on_low_volume_no_regression(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / "traces.jsonl"
            baseline_path = root / "baseline.json"
            now = datetime.now(timezone.utc)

            trace_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp_utc": (
                                    now - timedelta(hours=1)
                                ).isoformat(),
                                "tool_name": "benchmark_calls",
                                "summary": (
                                    "benchmark_calls success_rate=1.0 "
                                    "p95=10.0ms"
                                ),
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp_utc": (
                                    now - timedelta(hours=1)
                                ).isoformat(),
                                "tool_name": "scenario_load_test",
                                "summary": (
                                    "scenario_load_test success_rate=1.0 "
                                    "overall_p95=100.0ms"
                                ),
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            baseline_path.write_text(
                json.dumps(
                    {
                        "benchmark": {"insert_p95_ms": 10.0},
                        "scenario": {"latency_ms": {"overall_p95": 100.0}},
                    }
                ),
                encoding="utf-8",
            )

            result = evaluate_decision_gate(
                trace_path=trace_path,
                baseline_path=baseline_path,
                drift_bug_count=0,
                need_rust_portfolio=False,
            )
            self.assertTrue(result["ok"])
            self.assertFalse(result["migration_triggered"])

    def test_increment_drift_bug_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "drift_counter.json"
            first = increment_drift_bug_counter(path, note="bug one")
            second = increment_drift_bug_counter(path, note="bug two")
            self.assertEqual(first["count"], 1)
            self.assertEqual(second["count"], 2)


if __name__ == "__main__":
    unittest.main()
