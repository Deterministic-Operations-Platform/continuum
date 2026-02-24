# Evidence bundle contract and tamper evidence

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
- `site/index.html` includes an interactive dashboard UI (search, status filters, sorting, and KPI cards) for faster run triage.
- `runs/<run-id>/report.html` is rendered as a presentation-grade audit report with execution, policy, and tamper-evidence sections.
