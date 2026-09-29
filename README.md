# Continuum

<!-- portfolio-hero -->
![Continuum hero artwork](docs/assets/portfolio-hero.jpg)

Continuum is a standalone deterministic orchestration framework for regulated, high-stakes engineering workflows. It helps teams define replayable workflows, capture audit-grade evidence, enforce validation gates, and produce tamper-evident run bundles.

Continuum is **not** a Jira, Postman, Mongo, FedNow, or company-specific defect cockpit. The v0.1 demo uses mock payment-style steps only and contains no real credentials, real company data, or proprietary integrations.

## Install

Requires Python 3.10 or newer. From the repository root, create a virtual
environment and install the project:

```bash
python -m venv .venv
```

On Windows:

```powershell
.venv\Scripts\python -m pip install .
.venv\Scripts\continuum.exe --help
```

On macOS or Linux:

```bash
.venv/bin/python -m pip install .
.venv/bin/continuum --help
```

The repository root is the installable CLI. Run the example workflows below
from the repository root so their paths resolve.

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
- `bundle_signature.json` and `manifest.sha256` when bundle signing is enabled

## Bundle Signing

Continuum supports unsigned development runs, HMAC-SHA256 for existing CI integrations, and Ed25519 signatures for deployments that need independent public-key verification. HMAC keys must be at least 32 UTF-8 bytes. Production must set `CONTINUUM_SIGNING_REQUIRED=true` and explicitly choose `CONTINUUM_SIGNING_MODE`; missing signing configuration fails before workflow execution. Ed25519 verifiers trust an externally configured public-key ring; a public key copied into a run bundle is never accepted as a trust anchor. See [bundle signing and key rotation](docs/security/signing.md) for key formats, rotation requirements, environment variables, and the exact GitHub owner action.

## Documentation

- [Architecture](docs/architecture.md)
- [Evidence Model](docs/evidence-model.md)
- [Replay](docs/replay.md)
- [Bundle Signing and Key Rotation](docs/security/signing.md)
