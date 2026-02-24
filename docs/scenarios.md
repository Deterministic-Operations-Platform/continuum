# Scenario Schema (v0.1 Canonical)

Continuum uses one canonical runtime schema for YAML/JSON scenarios.

## Top-level contract

```yaml
name: string
rail: string
vars: {}                # optional run variables
services: {}            # optional service definitions
steps:                  # required, non-empty
  - name: string
    type: string
    key: string         # optional stable selector
    id: string          # optional alias for key
    with: {}            # optional plugin input
    always: false       # optional: run even if prior step failed
    dependsOn: []       # optional: list of step keys
    retry:              # optional
      on: [exception]
      maxAttempts: 1
      backoff: fixed
      baseDelayMs: 0
      maxDelayMs: 0
      jitter: 0.0
    publish:            # optional map from $.details.*
      varName: $.details.someField
cleanup_steps:          # optional best-effort cleanup steps
  - name: string
    type: string
    with: {}
```

## Templating

`with` values support interpolation:

- `${runId}` -> active run id
- `${runDir}` -> run evidence directory
- `${traceId}` -> active trace id
- `${env.NAME}` -> environment variable
- `${vars.someKey}` -> scenario vars or published vars

## Retries

Preferred explicit form:

```yaml
retry:
  on: [exception]
  maxAttempts: 3
  backoff: fixed
  baseDelayMs: 1000
  maxDelayMs: 1000
  jitter: 0.0
```

Legacy `with.retries` / `with.backoffMs` is still accepted and normalized.

## Cleanup semantics

`cleanup_steps` run after `steps` unless `--no-cleanup` is used.

## Live connectors (strict opt-in)

Jira and Mongo steps run in safe stub mode by default.

To execute live connector calls, enable both:

1. Step-level flag:
```yaml
with:
  live: true
```
2. Runtime env gate:
- `CONTINUUM_ENABLE_LIVE_CONNECTORS=1`
or connector-specific gates:
- `CONTINUUM_ENABLE_LIVE_JIRA=1`
- `CONTINUUM_ENABLE_LIVE_MONGO=1`

Additional live Jira env vars:
- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`

## Example

```yaml
name: fednow-camt29
rail: fednow
vars:
  issueKey: RTPAY-123
steps:
  - name: Run Postman
    key: run_postman
    type: postman.run
    with:
      collection: postman/camt29.collection.json
  - name: Verify Mongo
    type: mongo.verify
    dependsOn: [run_postman]
    with:
      uri: ${env.MONGO_URI}
      db: payments
```
