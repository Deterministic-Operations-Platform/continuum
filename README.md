# Continuum Orchestrator

Continuum is a deterministic, plugin-based orchestration engine for high-stakes workflow scenarios (for example FedNow), with audit-ready evidence generated for every run (including failures).

## v0.1 Deliverables
- Minimal CLI (`continuum status`, `continuum run <scenario>`)
- Scenario loader for YAML and JSON
- Evidence folder per run: `runs/<run-id>/scenario.*` + `runs/<run-id>/summary.json`
- Core interfaces for `Runtime`, `Plugin`, and `EvidenceCollector`

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
continuum status
```

## Run a scenario
```bash
continuum run examples/fednow-cam29-success.yaml --run-id local-001
```

If a plugin is missing, execution fails deterministically and still writes evidence to `runs/<run-id>/summary.json`.

## Scenario format (v0.1)
`steps` support either explicit plugin/action format:

```yaml
name: sample-explicit
rail: fednow
steps:
  - plugin: default
    action: ping
    input:
      message: hello
```

Or short action format:

```yaml
name: sample-short
rail: fednow
steps:
  - ping:
      via: default
      message: hello
```

## Non-goals in v0.1
- No UI or web server
- No Spring Boot
- Rail logic remains in scenario data + plugins, not in core runtime
