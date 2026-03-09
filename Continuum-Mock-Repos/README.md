# Continuum Mock Repos

This workspace contains 15 lightweight, structurally consistent mock repositories for testing `repo-engine` and `workflow-core`.

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

A reusable scaffold source is also provided in `_template/`.
