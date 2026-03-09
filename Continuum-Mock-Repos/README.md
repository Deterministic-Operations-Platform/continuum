# Continuum-Mock-Repos

Company-style mock workspace container for **independent** Continuum repositories.

## Upgraded behavioral-testing layout
- Shared dependency relationships are encoded in each repo `build.gradle.kts` and `repo-metadata.yaml`.
- Event-focused repos include request/response models, mapper, validator, service, and handler/controller layers.
- Intentional defects are documented in `BUG_SEEDS.md` and surfaced by failing tests in selected repos.
- Task mapping metadata is available via `repo-metadata.yaml` in every repo.
- Mixed repo states can be simulated using `repo-states/*.state` and `tools/describe-repo-state.sh`.

## Layout convention (per repo)
- `build.gradle.kts`
- `settings.gradle.kts`
- `repo-metadata.yaml`
- `src/main/java/com/continuum/mock/Main.java`
- `src/main/resources/application.yaml`
- `src/main/resources/mock-scenarios.json`
- `README.md`

## Repositories
See `repos.txt` for the canonical list used by discovery tooling.

## Repo-engine compatibility
- Workspace-level discovery metadata: `workspace.yaml`
- Canonical repo list: `repos.txt`
- Per-repo metadata: `<repo>/.repo-engine.yaml`
- Inbound/outbound/platform signals are encoded in each repo metadata file.

## Initialize each repo as separate git repositories
```bash
./init-repos.sh
```

## No monorepo coupling
The workspace intentionally has **no** root `settings.gradle*`, `build.gradle*`, or shared multi-project include file.
Build and run commands must be executed from inside each repository directory.
