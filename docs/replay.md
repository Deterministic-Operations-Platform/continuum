# Deterministic Replay

`continuum replay <run-dir>` replays a previous workflow run by reading `inputs/workflow.yaml` from the run bundle. Continuum writes a new `runs/replay-<source-run-id>/` bundle and compares its `outputs_snapshot.json` with the source run.

Replay succeeds when the normalized output snapshots are identical. Replay reports drift when outputs differ, which can indicate code changes, workflow changes, environmental nondeterminism, or tampering.

Example:

```bash
continuum run examples/workflows/demo.yaml --run-id demo-v01
continuum replay runs/demo-v01
```

The replay run contains `replay_report.json` with source and replay hashes.
