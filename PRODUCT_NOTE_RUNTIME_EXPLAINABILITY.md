# Product Note: Runtime Explainability

## Main use case

Incident explanation and execution replay for the data runtime itself.

The system should answer:

- what happened during a run,
- why a command succeeded or failed,
- how state changed,
- where retries, drift, or bottlenecks appeared.

## Value proposition

Make the runtime explainable, not just runnable.

Instead of raw traces and scattered outputs, give one structured explanation of execution, failure cause, and state transition path.

## Data and signals to store

- canonical event type: `command.start`, `command.success`, `command.error`
- `run_id`
- `correlation_id` or parent event link
- command name, adapter name, or source
- idempotency key
- payload hash
- scope, `root_dir`, and table
- attempt number
- retry classification
- `latency_ms`
- dry-run predicted effects
- actual effects
- decision reason or rejection reason
- `before_state_hash` and `after_state_hash`
- changed rows or changed entities summary
- error class and error text
- dependency node or upstream cause
- invariant check results: idempotency, single write path, event coverage

## MVP feature for this repository

`explain_run`

An MCP tool that takes a `run_id` or a trace slice and returns:

- ordered execution timeline
- which operations ran
- where retries or errors happened
- what state changed
- why the final outcome happened
- whether runtime behavior matched expected design invariants

## Example outputs

- "Run X initialized engine, inserted row, rebuilt index, then failed in e2e because DuckDB execution path was unavailable."
- "Dry run predicted one write and no retries; actual run produced 3 retries and one terminal error."
- "Single write path preserved, event coverage complete, idempotency not violated."
