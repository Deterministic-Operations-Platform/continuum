# Continuum Orchestrator (v0.1)

Continuum is a deterministic, plugin-based Python orchestration engine for high-stakes workflow scenarios (for example FedNow), with audit-ready evidence produced on every run, including failures.

For v0.1, Python is the executable engine and source of truth. TS/Java implementations are parked under `experimental/` until they match the same runtime contract.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
continuum status
```

## CLI commands

`continuum status`
- Runtime health/status and available commands/plugins.

`continuum run <scenario> [--run-id ...]`
- Execute a scenario deterministically and emit a run bundle under `runs/<run-id>/`.

`continuum validate <scenario>`
- Validate scenario contract, plugin availability, and template references without executing.

`continuum plan <scenario> [--run-id ...]`
- Build and print deterministic execution plan. If `--run-id` is given, writes `runs/<run-id>/plan.json`.

`continuum publish --run-id <id> [--runs-dir runs] [--site-dir site] [--keep-runs 25]`
- Publish a run bundle to static HTML/JSON under `site/`.

## Canonical scenario schema (v0.1)

```yaml
name: string
rail: string
vars: {}               # optional
services: {}           # optional
steps:                 # required, non-empty
  - name: string
    type: string
    key: string        # optional (or id)
    id: string         # optional (alias for key)
    with: {}           # optional input payload
    always: false      # optional
    dependsOn: []      # optional array of step keys
    retry:             # optional
      on: [exception]
      maxAttempts: 1
      backoff: fixed
      baseDelayMs: 0
      maxDelayMs: 0
      jitter: 0.0
    publish:           # optional map of vars from $.details.*
      outputVar: $.details.some.field
cleanup_steps:         # optional
  - name: string
    type: string
    with: {}
```

## Evidence bundle contract

Every run writes:
- `runs/<run-id>/scenario.yaml`
- `runs/<run-id>/context.json`
- `runs/<run-id>/summary.json`
- `runs/<run-id>/manifest.json`

`events.log` may also be present depending on plugin/runtime behavior.

## Run example
```bash
continuum run examples/fednow-cam29-success.yaml --run-id local-001
continuum publish --run-id local-001
```

## Additional guides
- Scenario schema details: `docs/scenarios.md`
- FedNow local run guide: `docs/fednow-local-run-guide.md`
- FedNow runbook: `docs/FEDNOW_RUNBOOK.md`
