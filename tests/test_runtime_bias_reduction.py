from __future__ import annotations

import unittest

from mini_pg_like import EventLog, InsertAdapter, MiniPostgresLikeDB, WriteCore


class RuntimeBiasReductionTests(unittest.TestCase):
    def test_write_core_returns_cached_result_for_same_idempotency_payload(self) -> None:
        db = MiniPostgresLikeDB()
        db.create_table("orders", ["order_id", "customer_id", "amount"])
        write_core = WriteCore(adapter=InsertAdapter(db), event_log=EventLog())
        command = {
            "run_id": "run-1",
            "source": "test",
            "scope": "orders",
            "idempotency_key": "seed-1",
            "payload": {
                "table": "orders",
                "rows": [{"order_id": 1, "customer_id": 4242, "amount": 10}],
            },
        }

        first = write_core.execute(command)
        second = write_core.execute(command)

        self.assertEqual(first, second)
        self.assertEqual(len(db.tables["orders"].rows), 1)
        self.assertEqual(write_core.event_log.events[-1].attempt, 0)

    def test_write_core_rejects_same_idempotency_key_with_different_payload(self) -> None:
        db = MiniPostgresLikeDB()
        db.create_table("orders", ["order_id", "customer_id", "amount"])
        write_core = WriteCore(adapter=InsertAdapter(db), event_log=EventLog())

        write_core.execute(
            {
                "run_id": "run-1",
                "source": "test",
                "scope": "orders",
                "idempotency_key": "seed-1",
                "payload": {
                    "table": "orders",
                    "rows": [{"order_id": 1, "customer_id": 4242, "amount": 10}],
                },
            }
        )

        with self.assertRaisesRegex(
            ValueError, "idempotency conflict: same key with different payload"
        ):
            write_core.execute(
                {
                    "run_id": "run-2",
                    "source": "test",
                    "scope": "orders",
                    "idempotency_key": "seed-1",
                    "payload": {
                        "table": "orders",
                        "rows": [{"order_id": 1, "customer_id": 4242, "amount": 99}],
                    },
                }
            )
