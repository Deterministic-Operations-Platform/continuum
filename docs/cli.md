# Full CLI catalog

`continuum status`
- Runtime health/status and available commands/plugins.

`continuum run <scenario> [--run-id ...]`
- Execute a scenario deterministically and emit a run bundle under `runs/<run-id>/`.
- Supports resume/selective execution, optional replay of succeeded steps (`--replay-succeeded`), `--max-parallel`, RBAC actor/roles, approval-file governance checks, and policy-gated evidence checks (`policy.yaml` or `--policy-file`).

`continuum golden-run [--scenario scenarios/fednow/rtpay-golden.yaml]`
- One command for the FedNow/RTPay golden path: preflight, AppLauncher ensure, Postman run, Mongo verify, log correlation, Jira comment/attach, and publish-ready evidence.

`continuum validate <scenario>`
- Validate scenario against the canonical schema plus runtime/plugin preflight checks without executing.

`continuum ci <scenario> [--run-id ...]`
- CI workflow mode: validate, execute, and publish evidence in one command with non-zero exit on failures.

`continuum plan <scenario> [--run-id ...]`
- Build and print deterministic execution plan. If `--run-id` is given, writes `runs/<run-id>/plan.json`.

`continuum publish --run-id <id> [--runs-dir runs] [--site-dir site] [--keep-runs 25]`
- Publish a run bundle to static HTML/JSON under `site/` using the shareable Evidence Viewer index (trace/git compare metadata).

`continuum verify --run-id <id> [--runs-dir runs]`
- Verify run policy result and bundle signature integrity.

`continuum keygen [--out-dir .continuum/keys] [--name continuum-ed25519]`
- Generate an Ed25519 keypair for bundle signing and public-key verification workflows.

`continuum serve [--site-dir site] [--host 127.0.0.1] [--port 8080]`
- Serve published run reports locally for browser access.

## Run examples
```bash
continuum run examples/fednow-cam29-success.yaml --run-id local-001
continuum publish --run-id local-001

continuum golden-run --actor release.user --role release-manager
```
