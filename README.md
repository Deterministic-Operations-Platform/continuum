# Continuum Orchestrator (v0.1)

Continuum is a deterministic, plugin-based Python orchestration engine for high-stakes workflow scenarios (for example FedNow), with audit-ready evidence produced on every run, including failures.

"Continuum turns high-stakes engineering work into deterministic, replayable runs with audit-ready evidence so banks can ship faster without increasing risk."

For v0.1, Python is the executable engine and source of truth. TS/Java implementations are parked under `experimental/` until they match the same runtime contract.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
npm install newman --prefix ./.continuum/vendor/npm --cache ./.continuum/npm-cache
continuum status
```

## CLI commands

`continuum status`
- Runtime health/status and available commands/plugins.

`continuum run <scenario> [--run-id ...]`
- Execute a scenario deterministically and emit a run bundle under `runs/<run-id>/`.
- Supports resume/selective execution, `--max-parallel`, RBAC actor/roles, approval-file governance checks, and policy-gated evidence checks (`policy.yaml` or `--policy-file`).

`continuum golden-run [--scenario scenarios/fednow/rtpay-golden.yaml]`
- One command for the FedNow/RTPay golden path: preflight, AppLauncher ensure, Postman run, Mongo verify, log correlation, Jira comment/attach, and publish-ready evidence.

`continuum validate <scenario>`
- Validate scenario against the canonical schema plus runtime/plugin preflight checks without executing.

`continuum ci <scenario> [--run-id ...]`
- CI workflow mode: validate, execute, and publish evidence in one command with non-zero exit on failures.

`continuum plan <scenario> [--run-id ...]`
- Build and print deterministic execution plan. If `--run-id` is given, writes `runs/<run-id>/plan.json`.

`continuum publish --run-id <id> [--runs-dir runs] [--site-dir site] [--keep-runs 25]`
- Publish a run bundle to static HTML/JSON under `site/` using the shareable Evidence Viewer index (trace/git compare metadata).

`continuum serve [--site-dir site] [--host 127.0.0.1] [--port 8080]`
- Serve published run reports locally for browser access.

## Live connector gates

Jira and Mongo plugins default to safe/stub mode. To execute live calls:

- Set `with.live: true` on the step.
- Set runtime gate env var: `CONTINUUM_ENABLE_LIVE_CONNECTORS=1`
  - Or connector-specific: `CONTINUUM_ENABLE_LIVE_JIRA=1`, `CONTINUUM_ENABLE_LIVE_MONGO=1`
- For Jira live mode, also set:
  - `JIRA_BASE_URL`
  - `JIRA_EMAIL`
  - `JIRA_API_TOKEN`

## Canonical scenario schema (v0.1)

```yaml
name: string
rail: string
vars: {}               # optional
services: {}           # optional
governance: {}         # optional
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
- `runs/<run-id>/bundle_signature.json`
- `runs/<run-id>/report.html`

`events.log` may also be present depending on plugin/runtime behavior.
- `events.log` is append-only with hash chaining (`prevHash` -> `hash`) for tamper-evident audit history.
- `manifest.json` includes per-artifact checksums plus an artifact-set checksum, and `bundle_signature.json` + `manifest.sha256` provide immutable integrity evidence.
- `site/index.html` is a shareable Evidence Viewer with searchable run comparison fields (`status`, `traceId`, `gitHead`).

## Run example
```bash
continuum run examples/fednow-cam29-success.yaml --run-id local-001
continuum publish --run-id local-001

continuum golden-run --actor release.user --role release-manager
```

## Additional guides
- Scenario schema details: `docs/scenarios.md`
- FedNow local run guide: `docs/fednow-local-run-guide.md`
- FedNow runbook: `docs/FEDNOW_RUNBOOK.md`
