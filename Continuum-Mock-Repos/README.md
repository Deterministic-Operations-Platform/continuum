# Continuum-Mock-Repos

Company-style mock workspace container for **independent** Continuum repositories.

## Workspace contract
- This parent folder is a **container only**.
- It is **not** a Gradle root project and **not** a monorepo build root.
- Each child folder is a standalone repository with its own build, source, config, and git lifecycle.

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
