# Generic Technical Design (Reusable)

Date: 2026-03-10  
Status: Reusable baseline for any product/project

## One-Liners (Quick Read First)

- Cross-layer first: every change is explained as `Idea -> API -> Runtime -> Storage -> Perf`.
- Reliability is non-negotiable: idempotency, controlled retries, observability, and safe reruns.
- One write path only: all mutations go through core validation and deterministic state transition.
- Event-first architecture: every command emits canonical start/success/error events with correlation IDs.
- DAG-driven execution: dependencies must be acyclic, measurable, and safe for parallelism.
- Adapter contract is fixed: `validate`, `dry_run`, `run`, `capabilities`.
- Claims must be computable: every roadmap item uses `Problem -> Ownership -> Actions -> Measurable Impact`.
- GO only with invariants + measurable KPIs + e2e critical flow pass.

## 1) Purpose

This document is a generic architecture and review framework.
Use it as the default technical design backbone for any new project.

Goals:
- reduce "magic" architectural discussions,
- enforce deterministic and auditable system behavior,
- make design decisions computable and testable.

## 2) Cross-Layer Design Model (Mandatory)

Every feature, incident, and architectural change must be described in 5 layers:

1. Idea
- What user/system pain is reduced?
- What business outcome is expected?

2. API/Contract
- Which command/event/API contract changes?
- Input/output schema?
- Validation and error model?

3. Runtime/Orchestration
- How is execution ordered?
- What retries/backoff are allowed?
- What is the failure and compensation strategy?

4. Storage/State
- What is canonical state?
- What event log is written?
- What isolation boundaries exist?

5. Perf/Cost
- Baseline metrics?
- Target metrics?
- Cost impact per operation/batch?

Cross-layer output rule:
- each design item must end with one concise summary line (one-liner) that can be used in reviews and handoffs.

## 3) Reliability Invariants (Mandatory)

R1. Idempotency
- Same idempotency key + same payload hash must return same logical result.
- Same idempotency key + different payload must return conflict.

R2. Controlled Retries
- Retry only retryable failures.
- Use bounded retries with exponential backoff + jitter.
- Log every attempt.

R3. Observability
- Emit canonical events for start/success/error.
- Every event must include correlation identifiers.

R4. Safe Reruns
- Reruns must not duplicate business entities or side effects.
- Replay/debug by run identifier must be possible.

R5. Deterministic State Transitions
- State can change only via declared intents/commands and deterministic reducers/handlers.
- No bypass direct writes from edge adapters.

## 4) Single-Write-Path Architecture Pattern

Principle:
- all write operations must pass through one core boundary.

Canonical flow:
1. Source emits intent/command.
2. Core validates scope, schema, policy, idempotency.
3. Core applies deterministic transition.
4. Core writes canonical state.
5. Core emits canonical event(s).

Non-goal:
- multiple independent write paths to the same business entity.

## 5) Dependency DAG and Execution Order

Execution model must be represented as a DAG:
- nodes: commands/jobs/stages,
- edges: dependency constraints.

Rules:
- no cycles in production execution graph,
- parallelism only for independent nodes,
- retries must preserve dependency correctness,
- critical path must be measurable.

Required DAG metrics:
- `critical_path_duration`,
- `queue_wait_p95`,
- `straggler_ratio`.

## 6) Adapter Interface Contract (Orchestration-Ready)

All integrations/adapters must implement one contract:
- `validate(input) -> validation_result`
- `dry_run(input) -> predicted_effects`
- `run(input) -> execution_result`
- `capabilities() -> capability_map`

Requirements:
- stable error taxonomy,
- retry policy declaration,
- deterministic serialization of input/output,
- explicit capability gating (what adapter is allowed to do).

## 7) Event-First Model

Event log is mandatory, server-side, canonical.

Required event types (minimum):
- `command.start`
- `command.success`
- `command.error`

Required event fields:
- `run_id`
- `source`
- `idempotency_key`
- `payload_hash`
- `attempt`
- `latency_ms`
- isolation keys (e.g., tenant/workspace/project context)

## 8) Isolation and Multi-Tenant Safety

Rules:
- every operation must include explicit isolation scope,
- cross-scope writes must be rejected,
- counters/sequences are scoped per isolation boundary,
- queries and metrics must support per-scope filtering.

## 9) Problem -> Ownership -> Actions -> Measurable Impact

Every roadmap item must be documented as:

Problem
- Concrete pain statement.
- Include denominator/base rate (avoid naive bias).

Ownership
- One accountable owner.
- One backup owner.
- SLA/response expectation.

Actions
- Specific implementation steps.
- Safety/rollback guards.

Measurable Impact
- Formula + baseline + target + observation window.
- Data source for metric computation.

## 10) Planner/Runtime Cost Model (Mandatory)

Design must explicitly include:
- expected input size/order of growth,
- selectivity/filter sharpness assumptions (where relevant),
- dominant bottleneck (CPU, memory, I/O, network, lock contention),
- asymptotic estimate plus real-world bottleneck note.

Minimum statement format:
- complexity estimate (example: `O(n)`, `O(n log n)`),
- expected practical bottleneck,
- optimization lever and expected effect.

## 11) Data Quality and Recovery

Mandatory quality controls:
- schema checks at ingress,
- business-rule assertions before publish,
- dedupe strategy,
- quarantine path for invalid data,
- replay/backfill procedure with run-scoped audit.

Mandatory recovery controls:
- rollback strategy for bad releases,
- deterministic replay by `run_id`,
- explicit RPO/RTO targets.

## 12) Generic KPI Bank

Use project-relevant subset:
- p95 command latency,
- error rate,
- retry amplification factor,
- stale/open ratio,
- duplicate-on-rerun rate,
- automation success rate,
- manual touchpoints per completed unit,
- time-to-first-action / time-to-triage.

Recommended reliability SLOs:
- MTTD (mean time to detect),
- MTTR (mean time to recover),
- success rate per critical flow.

## 13) Mathematical Core (Generic)

Deterministic transition:
- `S_(t+1) = R(S_t, I_t)`

Idempotency identity:
- `K = hash(scope, idempotency_key, payload_hash)`

Duplicate rerun metric:
- `rerun_duplicate_rate = duplicate_writes_after_rerun / rerun_writes`

Automation quality metric:
- `automation_success_rate = successful_actions / total_actions`

## 14) Go/No-Go Technical Gate

GO only if all pass:
- reliability invariants R1-R5,
- no write-path bypass,
- mandatory event coverage for all writes,
- measurable impact defined with formulas,
- e2e critical flow passes.

NO-GO if any fail:
- non-deterministic writes,
- missing idempotency on write operations,
- partial/missing event log,
- uncomputable KPI claims.

## 15) Review and Delivery Workflow

For each major change:
1. Fill Cross-Layer design.
2. Validate reliability invariants.
3. Run dry-run and e2e checks.
4. Publish decision with measurable impact targets.
5. Keep rollback path ready.

## 16) Recommended Companion Files

- `TECHNICAL_DESIGN_GENERIC.md` (this file)
- project-specific architecture appendix (optional)
- design review template
- runbook/incident playbook
- e2e critical flows checklist
