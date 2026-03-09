# Continuum Mock Repos

This workspace contains 15 lightweight, structurally consistent mock repositories for testing `repo-engine` and `workflow-core`.

## Layout convention (per repo)
- `build.gradle.kts`
- `settings.gradle.kts`
- `src/main/java/com/continuum/mock/Main.java`
- `src/main/java/com/continuum/mock/handler/HealthHandler.java`
- `src/main/java/com/continuum/mock/handler/WorkflowHandler.java`
- `src/main/resources/application.yaml`
- `src/main/resources/mock-scenarios.json`
- `README.md`

A reusable scaffold source is also provided in `_template/`.
