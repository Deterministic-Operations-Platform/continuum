# FedNow Runbook

## Prerequisites

- Python 3.10+ available on `PATH`.
- Repo checked out and shell opened at repo root:
  - `C:\Users\Nader Abdelshahid\continuum`
- Python dependencies installed:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  python -m pip install -r requirements.txt
  python -m pip install -e .
  ```
- Local integrations required by the FedNow example scenario:
  - `applauncher` (from `lifecycle.start`)
  - `transport-postman` (send step transport plugin)
  - `verify-mongo` (verification plugin against MongoDB)
- Scenario file:
  - `examples/fednow-cam29-success.yaml`

## Local Startup Order (AppLauncher and Dependencies)

Start dependencies before AppLauncher so lifecycle and verification checks can pass.

1. Start MongoDB (used by `verify-mongo`).
2. Start transport dependency used by `transport-postman` (Postman/Newman runner or local mock endpoint).
3. Start `applauncher`.
4. Confirm readiness for each dependency:
   - Mongo responds to `ping`.
   - Transport endpoint is reachable.
   - AppLauncher health/readiness check reports ready.

Use your local service start commands/scripts for each component.

## Scenario Execution Steps

1. Check CLI health:
   ```powershell
   continuum status
   ```
2. Run FedNow CAMT.029 example with an explicit run id:
   ```powershell
   continuum run examples/fednow-cam29-success.yaml --run-id run-fednow-local-001
   ```
3. Expected behavior:
   - Success path: run exits `0`.
   - Failure path: run exits non-zero, but evidence is still written to `runs/run-fednow-local-001`.

Notes:
- If `transport-postman` or `verify-mongo` are not registered in runtime, the run will fail deterministically with a plugin resolution error.
- This is expected in a scaffold environment until those plugins are wired.

## Evidence Review Steps

1. Confirm run directory exists:
   ```powershell
   Get-ChildItem runs/run-fednow-local-001
   ```
2. Review summary status and failure details:
   ```powershell
   $summary = Get-Content runs/run-fednow-local-001/summary.json -Raw | ConvertFrom-Json
   $summary.status
   $summary.failure
   ```
3. Validate scenario snapshot captured for audit:
   ```powershell
   Get-Content runs/run-fednow-local-001/scenario.yaml
   ```
4. If present, review additional evidence artifacts (Java scaffold path):
   - `runs/run-fednow-local-001/manifest.json`
   - `runs/run-fednow-local-001/events.log`

## Rollback and Cleanup Steps

1. Stop services in reverse order:
   1. AppLauncher
   2. Transport dependency
   3. MongoDB
2. Remove local run artifacts for this execution:
   ```powershell
   Remove-Item -Recurse -Force runs/run-fednow-local-001
   ```
3. Revert scenario-side test data in Mongo (if test records were inserted), for example by request reference.
4. Clear any local env vars or temporary config used only for this run.

## Troubleshooting Common Failures

| Symptom | Likely Cause | Action |
|---|---|---|
| `ModuleNotFoundError: No module named 'rich'` | Python deps not installed in active environment | Activate the intended venv and run `python -m pip install -r requirements.txt` and `python -m pip install -e .`. |
| `No plugin registered for 'transport-postman'` or `verify-mongo` | Required FedNow plugins are not registered in `PluginRegistry` | Register/inject those plugins before running FedNow scenarios, or run a smoke scenario using `default` plugin only. |
| `ScenarioValidationError` (missing fields or invalid steps) | Scenario schema does not match runtime parser | Validate YAML shape (`name`, `rail`, non-empty `steps`) and step format (`plugin/action` or short action mapping). The Java FEDNOW parser now also accepts UTF-8 BOM-prefixed files and `- action:` style short blocks with indented fields. |
| Run writes no artifacts or errors creating `runs/...` | Path/permissions issue on `runs` directory | Verify write access to repo workspace and rerun with a new run id. |
| `summary.json` shows `status: "STARTED"` only | Java scaffold CLI path writes static starter summary | Use as scaffold evidence output; for execution status details use the Python runtime path and its `summary.json` payload. |

