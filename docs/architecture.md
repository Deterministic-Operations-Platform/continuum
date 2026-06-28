# Continuum Architecture

Continuum is a standalone deterministic orchestration framework for regulated engineering workflows. It is intentionally not a defect cockpit or a product-specific connector bundle. The v0.1 architecture centers on:

- **Workflow definitions** in YAML or JSON with workflow id, steps, dependencies, inputs, expected outputs, validation gates, and evidence requirements.
- **Deterministic execution** using a topologically sorted plan and mock-safe step actions for reproducible demos.
- **Run bundles** under `runs/<run-id>/` containing manifests, logs, snapshots, validation reports, evidence indexes, and hash chains.
- **Validation gates** that fail fast on missing evidence or output-contract mismatches.
- **Replay** that re-executes from the captured workflow snapshot and compares output snapshots for drift.
- **Publishing and CI** commands that make run evidence consumable by static-site reports.

## Components

- `continuum.workflow`: v0.1 standalone workflow parser, validator, runner, replay engine, and hash-chain generator.
- `continuum.__main__`: CLI entrypoint for `validate`, `run`, `replay`, `ci`, `publish`, and `serve`.
- `runs/<run-id>`: immutable-style run evidence bundle.
- `examples/workflows/demo.yaml`: mock payment-style demonstration with no real credentials or proprietary data.

## Design Principles

1. Prefer deterministic data transforms over live side effects.
2. Capture enough evidence for independent audit.
3. Make every run replayable from its manifest and input snapshot.
4. Detect tampering through chained content hashes.
5. Keep regulated workflow controls generic and reusable.
