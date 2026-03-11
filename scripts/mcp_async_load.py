from __future__ import annotations

import asyncio
import math
import os
import statistics
import time
from collections import Counter
from dataclasses import dataclass

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER = StdioServerParameters(
    command=".venv/bin/python",
    args=["mcp_engine_server.py"],
    env={},
)


@dataclass(slots=True)
class CallResult:
    latency_ms: float
    ok: bool
    error_type: str | None = None


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = math.ceil((q / 100.0) * len(sorted_values)) - 1
    idx = max(0, min(idx, len(sorted_values) - 1))
    return sorted_values[idx]


async def call_insert(session: ClientSession, i: int) -> CallResult:
    started = time.perf_counter()
    try:
        await session.call_tool(
            "insert_row",
            {
                "root_dir": "./tests/artifacts/mcp/async_load",
                "table": "orders",
                "order_id": 100_000 + i,
                "customer_id": 4242 if i % 2 == 0 else 100,
                "amount": 10 + (i % 50),
            },
        )
        return CallResult(
            latency_ms=(time.perf_counter() - started) * 1000,
            ok=True,
        )
    except Exception as exc:  # noqa: BLE001
        return CallResult(
            latency_ms=(time.perf_counter() - started) * 1000,
            ok=False,
            error_type=type(exc).__name__,
        )


async def call_explain(session: ClientSession, i: int) -> CallResult:
    started = time.perf_counter()
    try:
        await session.call_tool(
            "explain_customer",
            {
                "root_dir": "./tests/artifacts/mcp/async_load",
                "table": "orders",
                "customer_id": 4242 if i % 2 == 0 else 100,
            },
        )
        return CallResult(
            latency_ms=(time.perf_counter() - started) * 1000,
            ok=True,
        )
    except Exception as exc:  # noqa: BLE001
        return CallResult(
            latency_ms=(time.perf_counter() - started) * 1000,
            ok=False,
            error_type=type(exc).__name__,
        )


async def call_upsert(session: ClientSession, i: int) -> CallResult:
    started = time.perf_counter()
    try:
        await session.call_tool(
            "upsert_row",
            {
                "root_dir": "./tests/artifacts/mcp/async_load",
                "table": "orders",
                "order_id": 100_000 + (i % 10),
                "customer_id": 4242 if i % 2 == 0 else 100,
                "amount": 100 + (i % 25),
            },
        )
        return CallResult(
            latency_ms=(time.perf_counter() - started) * 1000,
            ok=True,
        )
    except Exception as exc:  # noqa: BLE001
        return CallResult(
            latency_ms=(time.perf_counter() - started) * 1000,
            ok=False,
            error_type=type(exc).__name__,
        )


async def main() -> None:
    root_dir = "./tests/artifacts/mcp/async_load"
    total_calls = int(os.getenv("MCP_LOAD_CALLS", "60"))
    success_rate_slo = float(os.getenv("MCP_SLO_SUCCESS_RATE", "0.99"))
    p95_slo_ms = float(os.getenv("MCP_SLO_P95_MS", "250.0"))

    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool(
                "init_engine",
                {
                    "root_dir": root_dir,
                    "table": "orders",
                },
            )

            await session.call_tool(
                "create_index",
                {
                    "root_dir": root_dir,
                    "table": "orders",
                },
            )

            tasks: list[asyncio.Future[CallResult] | asyncio.Task[CallResult]] = []
            for i in range(total_calls):
                mode = i % 3
                if mode == 0:
                    tasks.append(asyncio.create_task(call_insert(session, i)))
                elif mode == 1:
                    tasks.append(asyncio.create_task(call_upsert(session, i)))
                else:
                    tasks.append(asyncio.create_task(call_explain(session, i)))

            results = await asyncio.gather(*tasks)
            latencies = [r.latency_ms for r in results]
            ok_count = sum(1 for r in results if r.ok)
            fail_count = len(results) - ok_count
            success_rate = ok_count / len(results) if results else 0.0
            p50 = percentile(latencies, 50)
            p95 = percentile(latencies, 95)
            avg = statistics.mean(latencies) if latencies else 0.0
            max_latency = max(latencies) if latencies else 0.0

            errors = Counter(r.error_type or "unknown" for r in results if not r.ok)

            print("call_count:", len(results))
            print("success_count:", ok_count)
            print("fail_count:", fail_count)
            print("success_rate:", round(success_rate, 4))
            print("latency_ms_avg:", round(avg, 2))
            print("latency_ms_p50:", round(p50, 2))
            print("latency_ms_p95:", round(p95, 2))
            print("latency_ms_max:", round(max_latency, 2))
            print("slo_success_rate_min:", success_rate_slo)
            print("slo_p95_ms_max:", p95_slo_ms)

            if errors:
                print("failure_breakdown:", dict(errors))
            else:
                print("failure_breakdown:", {})

            passed = success_rate >= success_rate_slo and p95 <= p95_slo_ms
            print("slo_passed:", passed)
            if not passed:
                raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
