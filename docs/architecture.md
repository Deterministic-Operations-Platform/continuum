# Architecture (starter)

**Core loop**
1. Ingest work (Jira issue / incident / change request)
2. Plan actions (policy + templates + guardrails)
3. Execute actions (repo changes, tests, DB verification, evidence capture)
4. Review gates (quality, security, approvals)
5. Ship (PR/merge/deploy) and log outcomes

**Core components**
- Orchestrator API (workflow engine)
- Connector runtime (Jira/GitHub/Postman/DB/CI)
- Evidence store (logs, screenshots, test reports)
- Policy engine (what’s allowed per team/environment)

## Error model and failure classification
Public execution surfaces should raise typed errors instead of generic exceptions:
- `ScenarioValidationError`: invalid scenario shape or missing required fields.
- `PluginResolutionError`: plugin/adapter not found or incompatible.
- `TransportError`: network/auth/protocol request failures.
- `VerificationError`: assertions failed or could not run.
- `LifecycleError`: lifecycle dependencies are not ready.
- `RuntimeTimeoutError`: timeout policy exceeded.

Failure classes are normalized for triage:
- **Infra failure**: dependency outage, network, auth, timeout.
- **Logic failure**: assertion mismatch, validation failure, unmet expectation.
- **Data failure**: missing persistence, state inconsistency, mapping errors.

## Determinism rules
- Steps execute in strict declared order.
- Retries follow an explicit policy (`max_attempts`, `backoff_seconds`).
- Scenario execution never depends on wall-clock randomness.
- Non-deterministic inputs (ids, timestamps, external tokens) are captured and emitted as evidence.

## Minimal scenario shape
```yaml
name: fednow-cam29-success
rail: fednow

lifecycle:
  start:
    - applauncher

steps:
  - send:
      via: transport-postman
      requestRef: cam29-valid
  - verify:
      via: verify-mongo
      collection: inbound_requests
      expect:
        addMeToMessage: true

evidence:
  export: audit-bundle
```
