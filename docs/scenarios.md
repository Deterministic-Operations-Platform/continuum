# Scenario schema (production profile)

Continuum scenarios define deterministic execution, retries/backoff, variable publishing, and guaranteed cleanup.

## Top-level schema

```yaml
name: string
rail: string
vars:                # optional run variables
  key: value
steps:               # required main execution steps
  - name: string
    type: string
    with:            # plugin input
      ...
    publish:         # optional: map vars from step result details
      varName: $.details.someField
cleanup_steps:       # optional: always runs after steps (best effort)
  - name: string
    type: string
    with: {}
```

## Templating

`with` fields support interpolation:

- `${runId}` → active run id
- `${runDir}` → run evidence directory
- `${env.NAME}` → environment variable lookup
- `${varName}` → value from scenario `vars` and published step outputs

## Retries and backoff

Every step may define retry controls under `with`:

```yaml
with:
  retries: 3
  backoffMs: 1000
```

Runtime records per-attempt metadata in `summary.json`.

## Publish outputs to vars

Each step can publish values from result details:

```yaml
publish:
  messageId: $.details.requestId
  traceId: $.details.trace.id
```

Expressions are dot-path lookups rooted at `$.details`.

## Teardown / cleanup semantics

`cleanup_steps` execute after main `steps` regardless of prior failure. Cleanup failures are captured in summary and can fail the run if no prior failure existed.

## Examples

### 1) ROF flow (skeleton)

```yaml
name: rof-daily
rail: rtpay
steps:
  - name: run-rof-collection
    type: postman.run
    with:
      collection: collections/rof-daily.postman_collection.json
      retries: 2
      backoffMs: 1000
```

### 2) CAMT-29 flow

```yaml
name: camt29
rail: fednow
steps:
  - name: send-camt29
    type: postman.run
    with:
      collection: collections/camt29.postman_collection.json
    publish:
      camt29Result: $.details.returncode
```

### 3) CAMT-56 flow with cleanup

```yaml
name: camt56
rail: fednow
steps:
  - name: start-service
    type: applauncher.start
    with:
      command: ./start-service.sh
    publish:
      servicePid: $.details.pid
  - name: health
    type: http.health
    with:
      url: http://127.0.0.1:8080/health
      retries: 5
      backoffMs: 500
cleanup_steps:
  - name: stop-service
    type: applauncher.stop
    with:
      pid: ${servicePid}
```

For a full production-like flow, see `examples/golden-fednow-rtpay.yaml`.
