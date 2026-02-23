# Continuum Orchestrator

Continuum is a deterministic, plugin-based orchestration engine for high-stakes workflow scenarios (for example FedNow), with audit-ready evidence generated for every run (including failures).

## v0.1 Deliverables
- Minimal CLI (`continuum status`, `continuum run <scenario>`)
- End-to-end deterministic run phases: preflight checks, lifecycle startup, transport/verification execution
- Scenario loader for YAML and JSON
- Evidence folder per run: `runs/<run-id>/scenario.*` + `summary.json` + `events.log` + `manifest.json`
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

## FEDNOW-only hardening updates
- `SimpleYamlParser` now ignores inline YAML comments in scalar values, including FEDNOW scenario metadata lines like `rail: fednow # payment rail`.
- `SimpleYamlParser` now also handles UTF-8 BOM-prefixed files and list items that use short action blocks (`- send:` followed by indented fields).
- `FileEvidenceCollector` now rejects blank artifact names and uses absolute, normalized path checks before writing evidence files.
- Scope intentionally excludes Java CLI command behavior (`ContinuumCli.java`) unless required for correctness.
- Reference guide: `docs/fednow-local-run-guide.md`

## End-to-end execution model
`continuum run` now enforces a deterministic sequence:
1. Preflight
   - Required plugins are available
   - Run artifact directory is writable
   - Scenario-defined checks (for example required environment variables) pass
2. Lifecycle startup
   - Services listed under `lifecycle.start` are started through lifecycle plugins
3. Scenario execution
   - Transport and verification steps run in order
4. Evidence emission
   - `summary.json`, `events.log`, and `manifest.json` are written for every run

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

## Additional guides
- GitHub Packages starter: `docs/github-packages-get-started.md`
