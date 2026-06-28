# Evidence Model

Every Continuum workflow run creates a run folder with audit-grade evidence:

- `manifest.json`: run identity, workflow id, status, timing, source path, input/output hashes, step plan, and hash-chain head.
- `inputs/workflow.yaml`: exact workflow snapshot used by the run.
- `inputs_snapshot.json`: normalized workflow inputs.
- `outputs/<step-id>.json`: deterministic step outputs.
- `outputs_snapshot.json`: complete step-output map.
- `logs/<step-id>.log`: readable per-step execution log.
- `validation_result.json`: validation gate result and errors.
- `evidence_index.json`: evidence file paths and SHA-256 digests.
- `hash_chain.json`: ordered tamper-evident records linking each step to the prior step hash.

Evidence requirements can be declared globally or per step. The `evidence-required` gate fails a run if a gated step has no evidence files.
