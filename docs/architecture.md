# Continuum Orchestrator — Architecture

## Purpose
Continuum is a deterministic orchestration engine for executing regulated engineering workflows end-to-end.

A workflow (called a **Scenario**) is defined as data (YAML/JSON) and executed by a runtime that:
- boots required dependencies (optional lifecycle)
- sends requests (transport)
- performs verifications (DB/log/state)
- produces audit-ready evidence artifacts for every run

Continuum intentionally avoids:
- UI / dashboards
- web servers / REST controllers
- probabilistic “AI-driven” execution logic in the core

The goal is correctness, repeatability, and auditability.

---

## Non-Negotiable Principles
1. **Deterministic execution**
   - Same inputs must produce the same results (within the same environment).
2. **Scenario-as-data**
   - Domain logic is expressed as scenario specs, not embedded in runtime code.
3. **Plugin isolation**
   - All external interactions happen via plugins behind interfaces.
4. **Evidence-first**
   - Evidence is produced automatically for every step and every run.
5. **Rail-agnostic core**
   - FedNow/RTP/other rails must not leak into core runtime code.

---

## System Overview

### High-level flow
1. User runs CLI: `continuum run <scenario>`
2. CLI loads scenario definition (YAML/JSON)
3. Runtime validates scenario + resolves plugins
4. Optional lifecycle steps run (start/healthcheck dependencies)
5. Scenario steps execute sequentially
6. Verifications run after each step (or at defined checkpoints)
7. Evidence engine captures artifacts continuously
8. Runtime outputs a run summary + evidence bundle location

### Core components
- **CLI**: Entry point, argument parsing, output formatting
- **Scenario Engine**: Parses scenario specs, validates schema, builds execution plan
- **Runtime**: Executes plan deterministically, manages state, error classification
- **Plugin System**: Transport/Verify/Lifecycle implementations discovered + invoked
- **Evidence Engine**: Collects artifacts, formats, computes checksums, exports bundles

---

## Module Layout (Recommended)

```text
src/continuum/
  cli/
    main.py
    commands/run.py
  scenario/
    loader.py
    schema.py
    planner.py
  runtime/
    executor.py
    state.py
    errors.py
  plugins/
    base.py
    registry.py
    transport/
    verify/
    lifecycle/
  evidence/
    collector.py
    artifact.py
    bundle.py
  report/
    summary.py
```

### Responsibilities by module
- `cli/`: Parse command-line input and invoke runtime with explicit options.
- `scenario/`: Load YAML/JSON specs, validate strict schemas, and produce executable plans.
- `runtime/`: Execute steps in order, enforce deterministic behavior, and classify failures.
- `plugins/`: Provide extension points for external systems while keeping core isolated.
- `evidence/`: Persist step artifacts (logs, outputs, checksums, timestamps).
- `report/`: Render human-readable and machine-readable run summaries.

---

## Determinism and Auditability Controls
- Stable step ordering with no implicit concurrency in core execution path.
- Explicit timeouts/retries configured in scenario data.
- Immutable per-run evidence directory with content-hash checksums.
- Canonical run manifest containing scenario version, plugin versions, and environment metadata.
- Structured error taxonomy (`validation`, `transport`, `verification`, `lifecycle`, `runtime`).

---

## Plugin Contracts
Every plugin should implement a small, typed interface and return structured results:
- **Transport plugin**: Sends a request and returns normalized response data.
- **Verify plugin**: Evaluates postconditions against DB/log/state sources.
- **Lifecycle plugin**: Starts/stops/checks readiness of dependencies.

Core runtime only depends on plugin interfaces, never concrete rails or providers.

---

## Evidence Artifacts
A run should emit an auditable bundle containing at minimum:
- scenario spec snapshot
- step-by-step execution log
- transport request/response captures (redacted as needed)
- verification outputs
- lifecycle logs
- final summary with pass/fail + error codes
- checksum manifest for all artifacts

