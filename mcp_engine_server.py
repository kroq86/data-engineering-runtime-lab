from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_project_contract_tools import (
    configure_project_contract_tools,
    project_capabilities,
    project_capture_baseline,
    project_compare_baseline,
    project_manifest,
    project_run_regression,
    register_project_contract_tools,
)
from mcp_generic_project_state_tools import (
    configure_generic_project_state_tools,
    project_append_event,
    project_delete_entity,
    project_explain_run,
    project_export_state,
    project_get_entity,
    project_ingest_trace,
    project_list_entities,
    project_upsert_entity,
    register_generic_project_state_tools,
)
from mcp_project_heuristic_tools import (
    configure_project_heuristic_tools,
    project_list_heuristics,
    project_run_heuristic,
    register_project_heuristic_tools,
)
from mcp_engine_runtime import EngineOps, EngineService, SubprocessRunner
from mcp_engine_tools import register_engine_tools
from mcp_explainability import (
    configure_explainability_tools,
    demo_explain_concurrency_failure_storm,
    demo_explain_run,
    demo_explain_idempotency_conflict,
    demo_explain_run_failure,
    demo_explain_semantic_failure,
    explain_regression_suite,
    explain_run,
    register_explainability_tools,
)
from mcp_slo_tools import (
    benchmark_calls,
    capture_roi_baseline,
    configure_slo_tools,
    decision_gate,
    health_check,
    register_slo_tools,
    report_drift_bug,
    scenario_load_test,
)
from mcp_trace_tools import (
    configure_trace_tools,
    record_tool_trace,
    refresh_docs_path,
    refresh_trace_path,
    register_trace_tools,
    similar_incidents,
)
from mcp_schema_tools import (
    configure_schema_tools,
    register_schema_tools,
)
from trace_observability import (
    TraceStore,
)


# When running in Docker with -e WORKSPACE_ROOT=/workspace and -v ${workspaceFolder}:/workspace,
# schema_path and other workspace-relative paths resolve to the mounted project (e.g. threads).
WORKSPACE_ROOT_ENV = os.getenv("WORKSPACE_ROOT")
WORKSPACE = Path(WORKSPACE_ROOT_ENV).resolve() if WORKSPACE_ROOT_ENV else Path(__file__).resolve().parent
TARGET_DIR = WORKSPACE / "target" / "debug"
BIN_DIR_ENV = os.getenv("MINI_DATA_ENGINE_BIN_DIR")
if BIN_DIR_ENV:
    bin_dir = Path(BIN_DIR_ENV)
    if not bin_dir.is_absolute():
        BIN_DIR = (WORKSPACE / bin_dir).resolve()
    else:
        BIN_DIR = bin_dir
else:
    BIN_DIR = TARGET_DIR
ENGINE_BIN = BIN_DIR / "engine_cli"
E2E_BIN = BIN_DIR / "e2e_flow"
mcp = FastMCP("mini-data-engine")
TRACE_DB_DEFAULT = Path("./tests/artifacts/mcp/trace_store/traces.jsonl")
TRACE_REFRESH_STATE_DEFAULT = Path(
    "./tests/artifacts/mcp/trace_store/refresh_state.json"
)
DOCS_REFRESH_STATE_DEFAULT = Path(
    "./tests/artifacts/mcp/trace_store/docs_refresh_state.json"
)
BASELINE_SNAPSHOT_DEFAULT = Path(
    "./tests/artifacts/mcp/baseline/latest_baseline.json"
)
DRIFT_BUG_COUNTER_DEFAULT = Path(
    "./tests/artifacts/mcp/baseline/drift_bug_counter.json"
)
PROJECT_STATE_ROOT_DEFAULT = Path("./tests/artifacts/mcp/project_state")
PROJECT_HEURISTICS_ROOT_DEFAULT = Path("./tests/artifacts/mcp/project_heuristics")
SCHEMA_VALIDATION_ARTIFACTS_DEFAULT = Path("./tests/artifacts/mcp/schema_validation")


OPS: EngineOps = EngineService(
    workspace=WORKSPACE,
    engine_bin=ENGINE_BIN,
    e2e_bin=E2E_BIN,
    runner=SubprocessRunner(),
    exec_mode=os.getenv("MINI_DATA_ENGINE_EXEC_MODE", "session"),
)


def _trace_store(path: str | None = None) -> TraceStore:
    if path:
        return TraceStore(path=Path(path))
    return TraceStore(path=TRACE_DB_DEFAULT)


def _parse_csv_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}

ENGINE_TOOLS = register_engine_tools(mcp=mcp, ops=OPS)
init_engine = ENGINE_TOOLS["init_engine"]
insert_row = ENGINE_TOOLS["insert_row"]
upsert_row = ENGINE_TOOLS["upsert_row"]
create_index = ENGINE_TOOLS["create_index"]
explain_customer = ENGINE_TOOLS["explain_customer"]
reindex_project = ENGINE_TOOLS["reindex_project"]
run_e2e_flow = ENGINE_TOOLS["run_e2e_flow"]


configure_explainability_tools(
    trace_store_factory=_trace_store,
    init_engine=init_engine,
    insert_row=insert_row,
    create_index=create_index,
    explain_customer=explain_customer,
    run_e2e_flow=run_e2e_flow,
    health_check=health_check,
    benchmark_calls=benchmark_calls,
    scenario_load_test=scenario_load_test,
    workspace=WORKSPACE,
    engine_bin=ENGINE_BIN,
)
configure_trace_tools(
    trace_store_factory=_trace_store,
    trace_refresh_state_default=TRACE_REFRESH_STATE_DEFAULT,
    docs_refresh_state_default=DOCS_REFRESH_STATE_DEFAULT,
)
configure_slo_tools(
    record_tool_trace=record_tool_trace,
    init_engine=init_engine,
    insert_row=insert_row,
    upsert_row=upsert_row,
    reindex_project=reindex_project,
    explain_customer=explain_customer,
    run_e2e_flow=run_e2e_flow,
    trace_db_default=TRACE_DB_DEFAULT,
    baseline_snapshot_default=BASELINE_SNAPSHOT_DEFAULT,
    drift_bug_counter_default=DRIFT_BUG_COUNTER_DEFAULT,
)
configure_project_contract_tools(
    workspace=WORKSPACE,
    trace_db_default=TRACE_DB_DEFAULT,
    baseline_snapshot_default=BASELINE_SNAPSHOT_DEFAULT,
    explain_regression_suite=explain_regression_suite,
    capture_roi_baseline=capture_roi_baseline,
    benchmark_calls=benchmark_calls,
    scenario_load_test=scenario_load_test,
    explain_run=explain_run,
)
configure_generic_project_state_tools(
    workspace=WORKSPACE,
    state_root_default=PROJECT_STATE_ROOT_DEFAULT,
    trace_store_factory=_trace_store,
    explain_run=explain_run,
)
configure_project_heuristic_tools(
    workspace=WORKSPACE,
    analysis_root_default=PROJECT_HEURISTICS_ROOT_DEFAULT,
)
configure_schema_tools(
    workspace=WORKSPACE,
    state_root_default=PROJECT_STATE_ROOT_DEFAULT,
    artifacts_dir_default=SCHEMA_VALIDATION_ARTIFACTS_DEFAULT,
    schema_tools_bin=BIN_DIR / "schema_tools",
)
register_explainability_tools(mcp)
register_trace_tools(mcp)
register_slo_tools(mcp)
register_project_contract_tools(mcp)
register_generic_project_state_tools(mcp)
register_project_heuristic_tools(mcp)
register_schema_tools(mcp)


if __name__ == "__main__":
    mcp.run()
