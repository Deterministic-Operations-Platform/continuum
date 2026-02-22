# FEDNOW Scope Review

## In-scope findings

- `SimpleYamlParser` change is aligned to FEDNOW parsing stabilization: it now supports indented mapping blocks under container keys in addition to list blocks, and still rejects malformed mixed structures.
- Artifact creation under `runs/<run-id>` remains deterministic via `scenario.yaml`, `summary.json`, `events.log`, and `manifest.json` writes through `FileEvidenceCollector`.
- `FileEvidenceCollector` now reuses existing run directories instead of recursively deleting contents, which is the key Windows locked-file fix.
- FEDNOW docs updates are present in `README.md`, `docs/fednow-local-run-guide.md`, and `docs/FEDNOW_RUNBOOK.md`.

## Unrelated / should-be-excluded from FEDNOW fix scope

- Temporary and compiled artifacts were committed under `.tmp/**`.
- Runtime output artifacts were committed under `runs/**` (multiple example run IDs and nested directories).
- Python bytecode cache files were committed under `continuum/__pycache__/**`.
- Duplicate top-level Java source changes outside `src/main/java/**` were included (`cli/ContinuumCli.java`, `core/runtime/ContinuumRuntime.java`, and `evidence/collector/FileEvidenceCollector.java`), which are not required for the FEDNOW Java source-path fix.

## `src/main/java/continuum/cli/ContinuumCli.java` assessment

- **Required for FEDNOW fix**: Yes, but only the portions that (a) resolve run directory under `runs/<run-id>` safely and deterministically, and (b) route artifact creation through `FileEvidenceCollector` for reuse behavior.
- **Should be split**: The broader constructor/testability refactors and command-structure reshaping in this file are not strictly required to fix FEDNOW Windows reused-run-dir behavior; they should be separated into a follow-up commit to keep FEDNOW scope minimal.
