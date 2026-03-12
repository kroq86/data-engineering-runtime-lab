# Product Note: Runtime Copilot

## What It Is

`Runtime Copilot` is an MCP-native operational brain for runtimes, internal data systems, and engineering workflows.

It is not the runtime itself.
It is the intelligence layer around the runtime.

Teams connect it to an AI client through MCP and get a system that can:

- describe its own tool surface,
- expose operational defaults and state roots,
- run health and regression checks,
- explain failures with trace context,
- compare current behavior against a baseline,
- retrieve similar incidents from prior runs.

## Product Framing

Most engineering systems already have scripts, logs, tests, traces, benchmark jobs, and deployment gates.

What they usually do not have is one operational interface that can answer:

- what can this system do,
- what are its defaults,
- is it healthy right now,
- did behavior regress,
- what failed first,
- has this happened before,
- what should I look at next.

`Runtime Copilot` is that interface.

## Why It Exists

Operational work is usually fragmented:

- tests live in one place,
- runtime checks in another,
- traces in another,
- baseline snapshots in another,
- docs and prior incidents somewhere else,
- and the AI client sees only a pile of disconnected commands.

That makes humans and agents spend too much time gathering context before they can act.

`Runtime Copilot` turns that fragmented surface into one MCP-connected control plane.

## Core Promise

Connect one MCP server and get:

- self-discovery,
- explainable diagnostics,
- regression-aware verdicts,
- operational memory,
- machine-usable runtime context.

The result is not just automation.
It is a more legible runtime.

## Who It Is For

- platform engineers
- data engineers
- infrastructure and SRE teams
- teams building internal developer platforms
- teams that want AI clients to work through a controlled operational surface instead of raw shell access

## How To Think About It

`Runtime Copilot` is to runtime operations what a code copilot is to source code:

- not the database,
- not the scheduler,
- not the warehouse,
- not the workflow engine,
- but the intelligence layer that helps understand, verify, and operate them.

It sits above the runtime and below the user-facing AI interaction.

## Why MCP

MCP is the right transport for this product because it makes the operational surface:

- discoverable,
- callable by agents,
- structured,
- portable across MCP clients,
- and easy to connect without inventing a custom UI first.

The MCP server becomes the product interface.

## What The Current Surface Already Supports

The current repository already exposes the primitives needed for the first version:

- runtime operations such as `init_engine`, `insert_row`, `upsert_row`, `create_index`, `run_e2e_flow`
- explainability flows such as `explain_run` and failure-control demos
- trace ingestion and incident retrieval
- SLO and benchmark checks
- baseline capture and baseline comparison
- contract discovery through `project_manifest`, `project_capabilities`, `project_tool_catalog`, and `project_get_defaults`

That means the project is already moving from "toy MCP wrapper" toward a real product surface.

## Product-Level Capabilities

Version 1 of `Runtime Copilot` should be understood as delivering five product capabilities:

1. Self-description
The system can explain what tools exist, how they are grouped, and what defaults they use.

2. Operational diagnostics
The system can run health and scenario checks and return structured results instead of only shell output.

3. Explainable failure analysis
The system can summarize run history and tell the user what happened and where the path broke.

4. Regression awareness
The system can compare current behavior against prior baselines and classify regressions.

5. Operational memory
The system can retain trace history and retrieve similar incidents to help humans and agents reason faster.

## User Experience

The user does not need to learn the full internal codebase.

They connect the MCP server to an AI client and ask for:

- the available operational surface,
- the project defaults,
- a health check,
- a regression verdict,
- an explanation of a failed run,
- similar incidents from prior traces.

That is the beginning of a product, not just a tool bundle.

## Product Positioning

The strongest positioning for this repository is:

`Runtime Copilot is an MCP-native operational brain for runtimes and internal data systems: self-describing, explainable, regression-aware, and ready to plug into your AI client.`

Short version:

`Connect Runtime Copilot to your AI client and turn runtime operations into a discoverable, explainable, and regression-aware interface instead of a pile of scripts, logs, and tribal knowledge.`

## Why This Is Bigger Than A Demo

The underlying lab is still educational and local-first.

But the product layer is no longer just educational.

It points to a real category:

- AI-connected operational surfaces
- self-describing runtime adapters
- explainable release and regression control planes
- operational memory systems for engineering teams

That is why `Runtime Copilot` works as a product idea.

## MVP Interpretation For This Repository

For this repository, the MVP is not "solve all DevOps".

The MVP is:

- package the MCP runtime cleanly,
- expose a self-discoverable tool catalog,
- expose defaults and state roots,
- keep explainability and regression entrypoints stable,
- make the system understandable enough that another MCP client can operate it with confidence.

That is already a credible v1.
