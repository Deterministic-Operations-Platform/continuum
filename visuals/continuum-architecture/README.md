# Continuum Architecture Experience

Interactive, vendor-neutral visualization of Continuum's deterministic workflow path:

`workflow YAML/JSON → dependency graph → deterministic execution → validation gates → evidence → logs/output snapshots → SHA-256 hash chain → run bundle → replay`

## Run locally

From the repository root:

```bash
python -m http.server 8080 -d visuals/continuum-architecture
```

Then open `http://localhost:8080`.

The experience is self-contained and uses local illustrative data only. It does not call external systems.

## Source alignment

The visualization is grounded in:

- `README.md`
- `docs/architecture.md`
- `docs/evidence-model.md`
- `docs/replay.md`
- `examples/workflows/demo.yaml`
- `continuum/workflow.py`
- `continuum/evidence.py`
- `continuum/runtime.py`
- `continuum/signing.py`

The interactive example uses the real v0.1 workflow schema and supported deterministic `mock` action pattern, but uses vendor-neutral engineering terminology rather than company- or rail-specific examples.

## Accuracy guardrails

- Continuum is described as deterministic, replayable, and auditable.
- SHA-256 integrity is described as **tamper-evident**, not tamper-proof.
- Replay is represented as re-running the captured workflow snapshot and comparing output snapshots for drift.
- No Jira, FedNow, MongoDB, Postman, bank, or employer-specific positioning is used.
