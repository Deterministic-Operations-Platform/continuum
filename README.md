# Continuum

Continuum is a standalone deterministic orchestration framework for regulated, high-stakes engineering workflows. It helps teams define replayable workflows, capture audit-grade evidence, enforce validation gates, and produce tamper-evident run bundles.

Continuum is **not** a Jira, Postman, Mongo, FedNow, or company-specific defect cockpit. The v0.1 demo uses mock payment-style steps only and contains no real credentials, real company data, or proprietary integrations.

## CLI

```bash
continuum validate examples/workflows/demo.yaml
continuum run examples/workflows/demo.yaml --run-id demo-v01
continuum replay runs/demo-v01
continuum ci examples/workflows/demo.yaml --run-id demo-ci
continuum publish --run-id demo-v01
continuum serve --site-dir site
```

## Workflow Definition

Workflows are YAML or JSON files with:

- `workflow_id`
- `inputs`
- `expected_outputs`
- `steps`
- step `depends_on`
- step `expected_outputs`
- `validation_gates`
- `evidence_requirements`

See `examples/workflows/demo.yaml`.

## Run Bundle

Each run creates `runs/<run-id>/` with:

- run manifest
- step logs
- input snapshot
- output snapshot
- validation result
- evidence index
- hash chain

## Documentation

- [Architecture](docs/architecture.md)
- [Evidence Model](docs/evidence-model.md)
- [Replay](docs/replay.md)
