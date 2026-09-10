# Project Context

- **Project:** Continuum
- **Owner:** Deterministic Operations Platform / Nader Abdelshahid
- **Canonical repository:** `Deterministic-Operations-Platform/continuum`
- **Visibility:** Private
- **Purpose:** Deterministic, replayable orchestration framework with governed evidence.
- **Major architecture:** Workflow definitions, DAG dependencies and parallel execution, validation gates, retries/resume/replay, CLI and orchestrator packages, correlation/trace IDs, evidence bundles, policy/governance, redaction, and tamper-evident audit mechanisms.
- **Verified implementation:** Current source, examples, tests, and CLI documentation implement workflow validation/run/replay/CI/publish/serve paths and their supporting orchestration/evidence components; exact guarantees are defined by code and tests.
- **Boundaries:** Continuum is deterministic and replayable. GodModeAI is interactive/exploratory autonomous engineering. Do not merge the two or create `nnabdelshahid/Continuum`.
- **Security/privacy:** Redact secrets, constrain execution, preserve evidence integrity, authenticate integrations, and avoid sensitive payloads in logs or bundles.
- **Relationships:** Can orchestrate governed work across DeploymentPlatform and other services while remaining independent of GodModeAI's agent engine.
- **Cost principle:** Own the deterministic orchestration layer and build on open, portable components and formats.
- **Known TODOs:** Use current tests/issues as authority and address existing worktree hygiene separately without discarding changes.

Actual source code takes precedence over outdated documentation.
