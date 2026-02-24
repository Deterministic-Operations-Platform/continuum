# Continuum Orchestrator

Continuum is a deterministic, plugin-based orchestration engine for high-stakes workflows. It produces replayable runs and audit-ready evidence bundles so teams can ship faster without increasing risk.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
continuum status
```

## Core commands
- `continuum status` — show runtime health and available plugins.
- `continuum run <scenario>` — execute a scenario and write evidence under `runs/<run-id>/`.
- `continuum validate <scenario>` — validate scenario and runtime/plugin preflight checks.
- `continuum publish --run-id <id>` — publish a run bundle to `site/`.

## Scenario example
```yaml
name: fednow-happy-path
rail: fednow
steps:
  - name: run payment flow
    type: postman
    with:
      collection: collections/fednow.json
```

## Docs
- [Full CLI catalog](docs/cli.md)
- [Bundle signing modes and environment variables](docs/security/signing.md)
- [Live connector gates (Jira/Mongo)](docs/connectors/live-gates.md)
- [Canonical scenario schema](docs/scenario-schema.md)
- [Evidence bundle contract and tamper evidence](docs/evidence-bundle.md)
- [Maintainer repo admin (including repository transfer)](docs/maintainers/repo-admin.md)
- [Scenario guide](docs/scenarios.md)
- [FedNow local run guide](docs/fednow-local-run-guide.md)
- [FedNow runbook](docs/FEDNOW_RUNBOOK.md)
