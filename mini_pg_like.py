from __future__ import annotations

import hashlib
import json
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, List, Tuple

from sql_interview_queries import print_sql_interview_queries


@dataclass
class RowRef:
    """Pointer to a row in the heap table."""

    row_id: int


@dataclass
class PlannerCosts:
    """Planner knobs inspired by PostgreSQL cost parameters."""

    seq_page_cost: float = 1.0
    random_page_cost: float = 4.0
    cpu_tuple_cost: float = 0.01
    tuples_per_page: int = 128
    index_entries_per_page: int = 256


class BTreeNode:
    def __init__(self, leaf: bool = True) -> None:
        self.leaf = leaf
        self.keys: List[Any] = []
        self.values: List[List[RowRef]] = []  # only used in leaves
        self.children: List["BTreeNode"] = []  # only used in internal nodes


class BTreeIndex:
    """
    Educational B-tree index (not production-ready).
    - Supports duplicate keys by storing a list of RowRef per key.
    - Uses classic split-child insertion.
    """

    def __init__(self, order: int = 8) -> None:
        if order < 3:
            raise ValueError("B-tree order must be >= 3")
        self.order = order
        self.max_keys = order - 1
        self.root = BTreeNode(leaf=True)
        self.height = 1

    def _split_child(self, parent: BTreeNode, child_index: int) -> None:
        child = parent.children[child_index]
        mid = len(child.keys) // 2

        right = BTreeNode(leaf=child.leaf)
        right.keys = child.keys[mid + 1:]
        child_mid_key = child.keys[mid]

        if child.leaf:
            right.values = child.values[mid + 1:]
            child.values = child.values[:mid]
        else:
            right.children = child.children[mid + 1:]
            child.children = child.children[: mid + 1]

        child.keys = child.keys[:mid]

        parent.keys.insert(child_index, child_mid_key)
        parent.children.insert(child_index + 1, right)

    def insert(self, key: Any, row_ref: RowRef) -> None:
        root = self.root
        if len(root.keys) == self.max_keys:
            new_root = BTreeNode(leaf=False)
            new_root.children.append(root)
            self._split_child(new_root, 0)
            self.root = new_root
            self.height += 1
        self._insert_non_full(self.root, key, row_ref)

    def _insert_non_full(
        self, node: BTreeNode, key: Any, row_ref: RowRef
    ) -> None:
        if node.leaf:
            i = len(node.keys) - 1
            while i >= 0 and key < node.keys[i]:
                i -= 1

            if i >= 0 and node.keys[i] == key:
                node.values[i].append(row_ref)
                return

            node.keys.insert(i + 1, key)
            node.values.insert(i + 1, [row_ref])
            return

        i = len(node.keys) - 1
        while i >= 0 and key < node.keys[i]:
            i -= 1
        child_index = i + 1

        child = node.children[child_index]
        if len(child.keys) == self.max_keys:
            self._split_child(node, child_index)
            if key > node.keys[child_index]:
                child_index += 1

        self._insert_non_full(node.children[child_index], key, row_ref)

    def search(self, key: Any) -> List[RowRef]:
        return self._search_node(self.root, key)

    def _search_node(self, node: BTreeNode, key: Any) -> List[RowRef]:
        i = 0
        while i < len(node.keys) and key > node.keys[i]:
            i += 1

        if node.leaf:
            if i < len(node.keys) and node.keys[i] == key:
                return node.values[i]
            return []

        if i < len(node.keys) and key == node.keys[i]:
            # Internal separator key; search both boundary children
            # for duplicates.
            left_hits = self._search_node(node.children[i], key)
            right_hits = self._search_node(node.children[i + 1], key)
            return left_hits + right_hits

        return self._search_node(node.children[i], key)


class HeapTable:
    """Append-only heap table with tuple visibility simplified away."""

    def __init__(self, name: str, columns: List[str]) -> None:
        self.name = name
        self.columns = columns
        self.rows: List[Dict[str, Any]] = []

    def insert(self, row: Dict[str, Any]) -> RowRef:
        row_id = len(self.rows)
        self.rows.append(row)
        return RowRef(row_id=row_id)

    def fetch(self, row_ref: RowRef) -> Dict[str, Any]:
        return self.rows[row_ref.row_id]


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
    def __init__(self) -> None:
        self.events: List[CommandEvent] = []

    def emit(self, event: CommandEvent) -> None:
        self.events.append(event)


def _payload_hash(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class RetryableError(Exception):
    pass


def run_with_retries(
    fn: Any, max_attempts: int, base_delay_ms: int
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


class MiniPostgresLikeDB:
    """
    A toy DB that demonstrates:
    - Heap storage
    - B-tree index
    - Planner choice: Seq Scan vs Index Scan
    - EXPLAIN ANALYZE style output
    """

    def __init__(self, costs: PlannerCosts | None = None) -> None:
        self.tables: Dict[str, HeapTable] = {}
        self.indexes: Dict[Tuple[str, str], BTreeIndex] = {}
        self.distinct_stats: Dict[Tuple[str, str], Dict[Any, int]] = (
            defaultdict(dict)
        )
        self.costs = costs or PlannerCosts()

    def create_table(self, name: str, columns: List[str]) -> None:
        self.tables[name] = HeapTable(name=name, columns=columns)

    def _insert_row(self, table: str, row: Dict[str, Any]) -> None:
        tbl = self.tables[table]
        row_ref = tbl.insert(row)
        for (tbl_name, col), idx in self.indexes.items():
            if tbl_name == table:
                idx.insert(row[col], row_ref)

    def create_index(self, table: str, column: str, order: int = 32) -> None:
        tbl = self.tables[table]
        idx = BTreeIndex(order=order)
        distinct = defaultdict(int)
        for row_id, row in enumerate(tbl.rows):
            value = row[column]
            idx.insert(value, RowRef(row_id=row_id))
            distinct[value] += 1
        self.indexes[(table, column)] = idx
        self.distinct_stats[(table, column)] = dict(distinct)

    def _estimate_selectivity(
        self, table: str, column: str, value: Any
    ) -> float:
        tbl = self.tables[table]
        total = max(len(tbl.rows), 1)
        if (table, column) in self.distinct_stats:
            freq = self.distinct_stats[(table, column)].get(value, 0)
            return freq / total
        # No stats/index yet -> fallback heuristic
        return 0.20

    def _estimate_rows(
        self, table: str, column: str, value: Any
    ) -> Tuple[int, int]:
        total_rows = len(self.tables[table].rows)
        selectivity = self._estimate_selectivity(table, column, value)
        est_rows = max(1, int(total_rows * selectivity))
        return total_rows, est_rows

    def _seq_scan_cost(self, total_rows: int) -> float:
        pages = max(
            1,
            (total_rows + self.costs.tuples_per_page - 1)
            // self.costs.tuples_per_page,
        )
        io_cost = pages * self.costs.seq_page_cost
        cpu_cost = total_rows * self.costs.cpu_tuple_cost
        return io_cost + cpu_cost

    def _index_scan_cost(
        self, table: str, column: str, est_rows: int
    ) -> float:
        idx = self.indexes[(table, column)]

        # Root-to-leaf path and relevant leaf pages are random-access heavy.
        descent_cost = idx.height * self.costs.random_page_cost
        leaf_pages = max(
            1,
            (est_rows + self.costs.index_entries_per_page - 1)
            // self.costs.index_entries_per_page,
        )
        index_leaf_cost = leaf_pages * self.costs.random_page_cost

        # Heap fetches are modeled as random reads for matched rows.
        heap_pages = max(
            1,
            (est_rows + self.costs.tuples_per_page - 1)
            // self.costs.tuples_per_page,
        )
        heap_fetch_cost = heap_pages * self.costs.random_page_cost

        cpu_cost = est_rows * (self.costs.cpu_tuple_cost * 2.0)
        return descent_cost + index_leaf_cost + heap_fetch_cost + cpu_cost

    def explain_analyze_eq(self, table: str, column: str, value: Any) -> str:
        tbl = self.tables[table]
        has_index = (table, column) in self.indexes
        total_rows, est_rows = self._estimate_rows(table, column, value)
        seq_cost = self._seq_scan_cost(total_rows)
        idx_cost: float | None = None

        if has_index:
            idx_cost = self._index_scan_cost(table, column, est_rows)
            plan = "Index Scan" if idx_cost < seq_cost else "Seq Scan"
        else:
            plan = "Seq Scan"

        start = perf_counter()
        if plan == "Seq Scan":
            hits: List[Dict[str, Any]] = []
            removed = 0
            for row in tbl.rows:
                if row[column] == value:
                    hits.append(row)
                else:
                    removed += 1
            elapsed_ms = (perf_counter() - start) * 1000
            return (
                f"EXPLAIN ANALYZE\n"
                f"{plan} on {table}\n"
                f"  Filter: ({column} = {value!r})\n"
                f"  Estimated Cost: {seq_cost:.2f}\n"
                f"  Estimated Rows: {est_rows}\n"
                f"  Rows Removed by Filter: {removed}\n"
                f"  Actual Rows: {len(hits)}\n"
                f"  Execution Time: {elapsed_ms:.3f} ms\n"
            )

        idx = self.indexes[(table, column)]
        row_refs = idx.search(value)
        hits = [tbl.fetch(rr) for rr in row_refs]
        elapsed_ms = (perf_counter() - start) * 1000
        return (
            f"EXPLAIN ANALYZE\n"
            f"{plan} using {table}_{column}_idx on {table}\n"
            f"  Index Cond: ({column} = {value!r})\n"
            f"  Estimated Cost: {idx_cost:.2f}\n"
            f"  Estimated Rows: {est_rows}\n"
            f"  B-Tree Height: {idx.height}\n"
            f"  Heap Fetches: {len(hits)}\n"
            f"  Actual Rows: {len(hits)}\n"
            f"  Execution Time: {elapsed_ms:.3f} ms\n"
        )


class InsertAdapter:
    """Single write adapter for table inserts."""

    def __init__(self, db: MiniPostgresLikeDB) -> None:
        self.db = db

    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        table = input_data.get("table")
        rows = input_data.get("rows", [])
        if table not in self.db.tables:
            return {"ok": False, "error": "table does not exist"}
        if not isinstance(rows, list) or not rows:
            return {"ok": False, "error": "rows must be a non-empty list"}
        columns = set(self.db.tables[table].columns)
        for row in rows:
            if not columns.issubset(row.keys()):
                return {"ok": False, "error": "row missing required columns"}
        return {"ok": True}

    def dry_run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "table": input_data["table"],
            "row_count": len(input_data["rows"]),
        }

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        table = input_data["table"]
        for row in input_data["rows"]:
            self.db._insert_row(table, row)
        return {"ok": True, "inserted": len(input_data["rows"])}

    def capabilities(self) -> Dict[str, Any]:
        return {
            "operations": ["bulk_insert"],
            "retry_policy": {"max_attempts": 3, "base_delay_ms": 20},
        }


class WriteCore:
    """Core boundary: validation, idempotency, retries, events."""

    def __init__(self, adapter: InsertAdapter, event_log: EventLog) -> None:
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
                details={"table": payload.get("table")},
            )
        )

        existing_same_key = [
            k
            for k in self.idempotency_store
            if k.startswith(f"{scope}:{idem_key}:")
        ]
        if existing_same_key and idem_identity not in self.idempotency_store:
            raise ValueError(
                "idempotency conflict: same key with different payload"
            )

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
                    details={"cached": True},
                )
            )
            return cached

        validation = self.adapter.validate(payload)
        if not validation.get("ok"):
            raise ValueError(validation.get("error", "validation failed"))

        retry_cfg = self.adapter.capabilities()["retry_policy"]
        result, attempts = run_with_retries(
            fn=lambda: self.adapter.run(payload),
            max_attempts=int(retry_cfg["max_attempts"]),
            base_delay_ms=int(retry_cfg["base_delay_ms"]),
        )
        self.idempotency_store[idem_identity] = result

        latency_ms = (time.perf_counter() - start) * 1000
        self.event_log.emit(
            CommandEvent(
                event_type="command.success",
                run_id=run_id,
                source=source,
                idempotency_key=idem_key,
                payload_hash=payload_hash,
                attempt=attempts,
                latency_ms=latency_ms,
                scope=scope,
                details={"inserted": result.get("inserted", 0)},
            )
        )
        return result


def build_demo_data(core: WriteCore, rows: int = 100_000) -> None:
    payload_rows: List[Dict[str, Any]] = []
    for i in range(rows):
        # Distribution:
        # - customer_id=1 appears often (non-selective).
        # - customer_id=4242 appears rarely (selective).
        if i % 2 == 0:
            customer_id = 1
        elif i % 2000 == 1:
            customer_id = 4242
        else:
            customer_id = (i % 5000) + 2
        payload_rows.append(
            {
                "order_id": i + 1,
                "customer_id": customer_id,
                "amount": (i % 100) + 1,
            }
        )

    core.execute(
        {
            "run_id": "run_orders_seed_001",
            "source": "demo",
            "scope": "workspace:default",
            "idempotency_key": "orders-seed-v1",
            "payload": {"table": "orders", "rows": payload_rows},
        }
    )


def _legacy_build_demo_data(
    db: MiniPostgresLikeDB, rows: int = 100_000
) -> None:
    db.create_table("orders", ["order_id", "customer_id", "amount"])
    for i in range(rows):
        # Distribution:
        # - customer_id=1 appears often (non-selective).
        # - customer_id=4242 appears rarely (selective).
        if i % 2 == 0:
            customer_id = 1
        elif i % 2000 == 1:
            customer_id = 4242
        else:
            customer_id = (i % 5000) + 2
        db._insert_row(
            "orders",
            {
                "order_id": i + 1,
                "customer_id": customer_id,
                "amount": (i % 100) + 1,
            },
        )


def main() -> None:
    print("Mini PostgreSQL-like demo from B-tree theory\n")
    db = MiniPostgresLikeDB()
    db.create_table("orders", ["order_id", "customer_id", "amount"])
    event_log = EventLog()
    write_core = WriteCore(adapter=InsertAdapter(db), event_log=event_log)
    build_demo_data(write_core)

    print("1) Before creating index:")
    print(db.explain_analyze_eq("orders", "customer_id", 4242))

    db.create_index("orders", "customer_id", order=64)
    print("2) After creating B-tree index (selective predicate):")
    print(db.explain_analyze_eq("orders", "customer_id", 4242))

    print("3) After creating B-tree index (non-selective predicate):")
    print(db.explain_analyze_eq("orders", "customer_id", 1))

    print(
        "Why this mirrors PostgreSQL:\n"
        "- Heap table stores rows.\n"
        "- B-tree index stores key -> row references.\n"
        "- Planner picks Seq Scan for broad matches, "
        "Index Scan for selective ones.\n"
        "- All writes go through one core boundary with "
        "idempotency and canonical events.\n"
    )
    print(f"Canonical events emitted: {len(event_log.events)}\n")
    print_sql_interview_queries()


if __name__ == "__main__":
    main()
