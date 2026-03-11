from __future__ import annotations

import hashlib
import json
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Set, Tuple

from mini_pg_like import MiniPostgresLikeDB


@dataclass
class DeltaCommit:
    version: int
    timestamp_utc: str
    operation: str
    row_count: int


class MiniDeltaTable:
    """
    Delta-like table with version history and time-travel snapshots.
    This is educational and intentionally simplified.
    """

    def __init__(self, name: str, key_column: str) -> None:
        self.name = name
        self.key_column = key_column
        self._versions: List[List[Dict[str, Any]]] = [[]]
        self.log: List[DeltaCommit] = []

    @property
    def current_version(self) -> int:
        return len(self._versions) - 1

    def snapshot(self, version: int | None = None) -> List[Dict[str, Any]]:
        if version is None:
            version = self.current_version
        if version < 0 or version > self.current_version:
            raise ValueError("Invalid table version")
        return [row.copy() for row in self._versions[version]]

    def append(self, rows: List[Dict[str, Any]]) -> None:
        next_rows = self.snapshot()
        next_rows.extend(row.copy() for row in rows)
        self._commit("append", next_rows, len(rows))

    def merge_upsert(self, rows: List[Dict[str, Any]]) -> None:
        next_rows = self.snapshot()
        by_key: Dict[Any, Dict[str, Any]] = {
            r[self.key_column]: r for r in next_rows
        }
        for row in rows:
            by_key[row[self.key_column]] = row.copy()
        merged = list(by_key.values())
        self._commit("merge_upsert", merged, len(rows))

    def _commit(
        self, operation: str, new_rows: List[Dict[str, Any]], row_count: int
    ) -> None:
        self._versions.append(new_rows)
        self.log.append(
            DeltaCommit(
                version=self.current_version,
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                operation=operation,
                row_count=row_count,
            )
        )


@dataclass
class CommandEvent:
    event_type: str
    run_id: str
    source: str
    idempotency_key: str
    payload_hash: str
    attempt: int
    latency_ms: float
    scope: str
    details: Dict[str, Any]


class EventLog:
    """Canonical event log: command.start/success/error."""

    def __init__(self) -> None:
        self.events: List[CommandEvent] = []

    def emit(self, event: CommandEvent) -> None:
        self.events.append(event)


def _payload_hash(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class RetryableError(Exception):
    pass


class AdapterBase:
    """Adapter contract from TECHNICAL_DESIGN_GENERIC.md."""

    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()

    def dry_run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()

    def capabilities(self) -> Dict[str, Any]:
        raise NotImplementedError()


class OrdersWriteAdapter(AdapterBase):
    """Only write adapter for orders table (single write path)."""

    def __init__(self, table: MiniDeltaTable) -> None:
        self.table = table

    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        rows = input_data.get("rows", [])
        if not isinstance(rows, list) or not rows:
            return {"ok": False, "error": "rows must be a non-empty list"}
        for row in rows:
            required = {"order_id", "customer_id", "amount"}
            if not required.issubset(row.keys()):
                return {"ok": False, "error": "missing required order fields"}
        return {"ok": True}

    def dry_run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "operation": input_data["operation"],
            "row_count": len(input_data["rows"]),
            "predicted_next_version": self.table.current_version + 1,
        }

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = input_data["operation"]
        rows = input_data["rows"]
        if operation == "append":
            self.table.append(rows)
        elif operation == "merge_upsert":
            self.table.merge_upsert(rows)
        else:
            raise ValueError(f"unsupported operation: {operation}")
        return {
            "ok": True,
            "version": self.table.current_version,
            "row_count": len(rows),
        }

    def capabilities(self) -> Dict[str, Any]:
        return {
            "operations": ["append", "merge_upsert"],
            "retry_policy": {"max_attempts": 3, "base_delay_ms": 50},
        }


def run_with_retries(
    fn: Callable[[], Dict[str, Any]],
    max_attempts: int,
    base_delay_ms: int,
) -> Tuple[Dict[str, Any], int]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(), attempt
        except RetryableError as err:
            last_error = err
            if attempt == max_attempts:
                break
            jitter = random.randint(0, 25)
            delay_ms = base_delay_ms * (2 ** (attempt - 1)) + jitter
            time.sleep(delay_ms / 1000.0)
    if last_error is None:
        raise RuntimeError("retry loop failed without error")
    raise last_error


class WriteCore:
    """
    Core boundary for deterministic writes.
    Enforces validation, idempotency, retries, and canonical events.
    """

    def __init__(self, adapter: AdapterBase, event_log: EventLog) -> None:
        self.adapter = adapter
        self.event_log = event_log
        self.idempotency_store: Dict[str, Dict[str, Any]] = {}

    def execute(self, command: Dict[str, Any]) -> Dict[str, Any]:
        run_id = command["run_id"]
        source = command.get("source", "unknown")
        scope = command.get("scope", "default")
        idem_key = command["idempotency_key"]
        payload = command["payload"]
        payload_hash = _payload_hash(payload)
        idem_identity = f"{scope}:{idem_key}:{payload_hash}"

        start = time.perf_counter()
        self.event_log.emit(
            CommandEvent(
                event_type="command.start",
                run_id=run_id,
                source=source,
                idempotency_key=idem_key,
                payload_hash=payload_hash,
                attempt=1,
                latency_ms=0.0,
                scope=scope,
                details={"operation": payload.get("operation")},
            )
        )

        existing_same_key = [
            k for k in self.idempotency_store if k.startswith(f"{scope}:{idem_key}:")
        ]
        if existing_same_key and idem_identity not in self.idempotency_store:
            raise ValueError("idempotency conflict: same key with different payload")

        if idem_identity in self.idempotency_store:
            cached = self.idempotency_store[idem_identity]
            latency_ms = (time.perf_counter() - start) * 1000
            self.event_log.emit(
                CommandEvent(
                    event_type="command.success",
                    run_id=run_id,
                    source=source,
                    idempotency_key=idem_key,
                    payload_hash=payload_hash,
                    attempt=0,
                    latency_ms=latency_ms,
                    scope=scope,
                    details={"cached": True, "version": cached.get("version")},
                )
            )
            return cached

        validation = self.adapter.validate(payload)
        if not validation.get("ok"):
            latency_ms = (time.perf_counter() - start) * 1000
            self.event_log.emit(
                CommandEvent(
                    event_type="command.error",
                    run_id=run_id,
                    source=source,
                    idempotency_key=idem_key,
                    payload_hash=payload_hash,
                    attempt=1,
                    latency_ms=latency_ms,
                    scope=scope,
                    details={"error": validation.get("error", "validation failed")},
                )
            )
            raise ValueError(validation.get("error", "validation failed"))

        retry_cfg = self.adapter.capabilities().get("retry_policy", {})
        max_attempts = int(retry_cfg.get("max_attempts", 1))
        base_delay_ms = int(retry_cfg.get("base_delay_ms", 0))

        def _run_once() -> Dict[str, Any]:
            return self.adapter.run(payload)

        try:
            result, attempts_used = run_with_retries(
                fn=_run_once,
                max_attempts=max_attempts,
                base_delay_ms=base_delay_ms,
            )
        except Exception as err:
            latency_ms = (time.perf_counter() - start) * 1000
            self.event_log.emit(
                CommandEvent(
                    event_type="command.error",
                    run_id=run_id,
                    source=source,
                    idempotency_key=idem_key,
                    payload_hash=payload_hash,
                    attempt=max_attempts,
                    latency_ms=latency_ms,
                    scope=scope,
                    details={"error": str(err)},
                )
            )
            raise

        self.idempotency_store[idem_identity] = result
        latency_ms = (time.perf_counter() - start) * 1000
        self.event_log.emit(
            CommandEvent(
                event_type="command.success",
                run_id=run_id,
                source=source,
                idempotency_key=idem_key,
                payload_hash=payload_hash,
                attempt=attempts_used,
                latency_ms=latency_ms,
                scope=scope,
                details={"version": result.get("version"), "cached": False},
            )
        )
        return result


class MiniSparkEngine:
    """Tiny partition-based execution model."""

    def partition(
        self, rows: List[Dict[str, Any]], n_parts: int
    ) -> List[List[Dict[str, Any]]]:
        parts: List[List[Dict[str, Any]]] = [[] for _ in range(max(1, n_parts))]
        for idx, row in enumerate(rows):
            parts[idx % len(parts)].append(row)
        return parts

    def map_partitions(
        self,
        partitions: List[List[Dict[str, Any]]],
        fn: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]],
    ) -> List[List[Dict[str, Any]]]:
        return [fn(part) for part in partitions]

    def collect(self, partitions: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for part in partitions:
            out.extend(part)
        return out


class MiniWorkflow:
    """DAG workflow runner with topological ordering."""

    def __init__(self) -> None:
        self.tasks: Dict[str, Callable[[], None]] = {}
        self.deps: Dict[str, Set[str]] = defaultdict(set)
        self.children: Dict[str, Set[str]] = defaultdict(set)

    def add_task(
        self,
        task_id: str,
        task_fn: Callable[[], None],
        depends_on: List[str] | None = None,
    ) -> None:
        self.tasks[task_id] = task_fn
        for dep in depends_on or []:
            self.deps[task_id].add(dep)
            self.children[dep].add(task_id)

    def run(self) -> List[str]:
        in_degree: Dict[str, int] = {
            task: len(self.deps[task]) for task in self.tasks
        }
        q = deque(task for task, deg in in_degree.items() if deg == 0)
        order: List[str] = []

        while q:
            task_id = q.popleft()
            self.tasks[task_id]()
            order.append(task_id)
            for child in self.children[task_id]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    q.append(child)

        if len(order) != len(self.tasks):
            raise ValueError("Cycle detected in workflow DAG")
        return order

    def metrics(self, order: List[str]) -> Dict[str, float]:
        # Placeholder metrics for interview demonstration.
        return {
            "critical_path_duration": float(len(order)),
            "queue_wait_p95": 0.0,
            "straggler_ratio": 0.0,
        }


class MiniSQLWarehouse:
    """
    SQL serving facade backed by the mini cost-based planner.
    Supports only one pattern:
    SELECT * FROM <table> WHERE <column> = <value>;
    """

    def __init__(self) -> None:
        self.db = MiniPostgresLikeDB()

    def load_table(
        self, table: str, columns: List[str], rows: List[Dict[str, Any]]
    ) -> None:
        self.db.create_table(table, columns)
        for row in rows:
            self.db._insert_row(table, row)

    def create_index(self, table: str, column: str, order: int = 64) -> None:
        self.db.create_index(table, column, order=order)

    def explain_query_eq(self, table: str, column: str, value: Any) -> str:
        return self.db.explain_analyze_eq(table, column, value)


@dataclass
class MLRun:
    run_id: str
    params: Dict[str, Any]
    metrics: Dict[str, float]


class MiniMLflow:
    def __init__(self) -> None:
        self.runs: List[MLRun] = []
        self.models: Dict[str, str] = {}

    def log_run(
        self, run_id: str, params: Dict[str, Any], metrics: Dict[str, float]
    ) -> None:
        self.runs.append(MLRun(run_id=run_id, params=params, metrics=metrics))

    def register_model(self, model_name: str, run_id: str) -> None:
        self.models[model_name] = run_id


class MiniCatalog:
    """Basic access control list for datasets."""

    def __init__(self) -> None:
        self.permissions: Dict[str, Dict[str, Set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )

    def grant(self, principal: str, table: str, privilege: str) -> None:
        self.permissions[table][principal].add(privilege)

    def can(self, principal: str, table: str, privilege: str) -> bool:
        return privilege in self.permissions[table][principal]


def demo() -> None:
    print("Minimal Databricks-like clone demo\n")

    # 1) Delta-like table
    bronze = MiniDeltaTable(name="orders_bronze", key_column="order_id")
    event_log = EventLog()
    write_adapter = OrdersWriteAdapter(table=bronze)
    write_core = WriteCore(adapter=write_adapter, event_log=event_log)

    rows = []
    for i in range(1, 5001):
        customer_id = 4242 if i % 1000 == 0 else 1
        rows.append({"order_id": i, "customer_id": customer_id, "amount": i % 100})
    write_core.execute(
        {
            "run_id": "run_ingest_001",
            "source": "demo",
            "scope": "workspace:default",
            "idempotency_key": "orders-bronze-append-v1",
            "payload": {"operation": "append", "rows": rows},
        }
    )
    write_core.execute(
        {
            "run_id": "run_ingest_002",
            "source": "demo",
            "scope": "workspace:default",
            "idempotency_key": "orders-bronze-upsert-v1",
            "payload": {
                "operation": "merge_upsert",
                "rows": [{"order_id": 5000, "customer_id": 4242, "amount": 35}],
            },
        }
    )
    print(f"Delta current version: {bronze.current_version}")
    print(f"Version 1 snapshot rows: {len(bronze.snapshot(version=1))}")
    print(f"Version 2 snapshot rows: {len(bronze.snapshot(version=2))}")

    # 2) Spark-like partition processing
    spark = MiniSparkEngine()
    parts = spark.partition(bronze.snapshot(), n_parts=2)
    transformed = spark.map_partitions(
        parts,
        lambda p: [
            dict(r, amount_with_tax=round(r["amount"] * 1.2, 2))
            for r in p
        ],
    )
    silver_rows = spark.collect(transformed)
    print(f"Spark partitions: {len(parts)}, transformed rows: {len(silver_rows)}")

    # 3) SQL warehouse backed by cost-based planner
    warehouse = MiniSQLWarehouse()
    warehouse.load_table(
        table="orders_silver",
        columns=["order_id", "customer_id", "amount", "amount_with_tax"],
        rows=silver_rows,
    )
    print("\nSQL Warehouse (before index):")
    print(warehouse.explain_query_eq("orders_silver", "customer_id", 4242))
    warehouse.create_index("orders_silver", "customer_id")
    print("SQL Warehouse (after index):")
    print(warehouse.explain_query_eq("orders_silver", "customer_id", 4242))

    # 4) Workflow orchestration DAG
    workflow = MiniWorkflow()
    workflow.add_task("extract", lambda: None)
    workflow.add_task("transform", lambda: None, depends_on=["extract"])
    workflow.add_task("serve_sql", lambda: None, depends_on=["transform"])
    order = workflow.run()
    print(f"Workflow execution order: {order}")
    print(f"Workflow metrics: {workflow.metrics(order)}")

    # 5) MLflow-like tracking and model registry
    mlflow = MiniMLflow()
    mlflow.log_run(
        run_id="run_001",
        params={"model": "xgboost", "max_depth": 5},
        metrics={"rmse": 0.31},
    )
    mlflow.register_model("churn_model", "run_001")
    print(f"Registered model churn_model -> {mlflow.models['churn_model']}")

    # 6) Catalog/security
    catalog = MiniCatalog()
    catalog.grant("analyst_team", "orders_silver", "SELECT")
    print(
        "Catalog access analyst_team SELECT orders_silver:",
        catalog.can("analyst_team", "orders_silver", "SELECT"),
    )

    print(
        "\nLayer mapping:\n"
        "- Spark execution engine -> MiniSparkEngine\n"
        "- Delta storage layer -> MiniDeltaTable\n"
        "- Jobs/workflows -> MiniWorkflow\n"
        "- SQL warehouse -> MiniSQLWarehouse\n"
        "- ML tooling -> MiniMLflow\n"
        "- Governance/catalog/security -> MiniCatalog\n"
        "- Single write path + idempotency + events -> WriteCore/EventLog\n"
    )
    print(f"Canonical events emitted: {len(event_log.events)}")


if __name__ == "__main__":
    demo()
