# Core Contracts and Evidence Engine

This document defines the minimal interfaces for scenario execution, plugin integration, and immutable evidence output.

## 1) Scenario Contract

A **Scenario** is declarative input to a run.

```ts
interface Scenario {
  name: string;
  rail: string;
  lifecycle?: LifecycleConfig;
  steps: ScenarioStep[];
  evidence: EvidenceExportStrategy;
}
```

Required fields:
- `name`
- `rail` (informational label)
- `steps[]` (ordered)
- `evidence` (export policy)

Optional:
- `lifecycle`

## 2) Execution Plan Contract

An **ExecutionPlan** is a normalized in-memory object derived from a Scenario.

```ts
interface ExecutionPlan {
  runId: string;
  scenario: Scenario;
  lifecycle?: ResolvedLifecyclePlan;
  steps: ResolvedStepPlan[];
  evidencePolicy: EvidencePolicy;
  createdAt: string;
}
```

Execution plan guarantees:
- Plugin references are resolved.
- Step order and dependencies are validated.
- Evidence policies are precomputed.

## 3) Runtime Contract

Runtime responsibilities:
- Deterministic step execution
- Step-level timeout and retry handling (policy-driven)
- State transitions
- Structured result generation
- Error classification

Runtime constraints:
- Must **not** embed rail-specific business rules.
- Must **not** call Postman/Mongo/HTTP directly; all I/O must go through plugins.

## 4) Plugin Contracts

### Transport Plugin
Executes requests (HTTP, Postman, gRPC, etc.).

Input/Output expectations:
- request definition input
- structured response output
- evidence artifacts (request/response + metadata)

### Verification Plugin
Validates effects (DB state, logs, transitions).

Input/Output expectations:
- query/assertion definitions
- structured verification result
- evidence artifacts (query/snapshot/results)

### Lifecycle Plugin
Prepares and validates environment.

Input/Output expectations:
- optional start/stop hooks
- readiness checks
- evidence artifacts (health/logs)

## 5) Evidence Engine

Evidence is an immutable artifact set created for **every** run (including failures).

Evidence contents include:
- Scenario definition used
- Step inputs
- Step outputs
- Timestamps and durations
- Optional environment metadata
- Checksums for integrity

### Evidence requirements
- Always emitted, even on failure.
- Organized by run id + scenario name + timestamp.
- Machine-readable, stable artifact format.

## 6) Suggested Evidence Bundle Structure

```text
runs/
  <scenario-name>/
    <run-id>-<timestamp>/
      manifest.json
      scenario.json
      environment.json
      lifecycle/
        start.json
        readiness.json
        stop.json
      steps/
        001-<step-name>/
          input.json
          output.json
          artifacts/
            request.json
            response.json
            metadata.json
            checksums.sha256
        002-<step-name>/
          ...
      summary.json
      checksums.sha256
```

### Suggested file semantics
- `manifest.json`: index of bundle files, checksums, versions.
- `summary.json`: run status, timings, failed step, error classification.
- `checksums.sha256`: integrity hash list for all evidence files.

## 7) Error Classification (recommended)

Standard runtime categories:
- `timeout`
- `plugin_error`
- `assertion_failed`
- `dependency_failed`
- `configuration_error`
- `runtime_error`

Consistent classification enables deterministic retries, summary reporting, and policy routing.
