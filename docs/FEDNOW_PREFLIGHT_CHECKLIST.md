# FEDNOW Plugin Readiness Preflight (Checklist + PowerShell)

## Purpose
Use this preflight before FEDNOW scenario execution to catch missing dependencies early (AppLauncher, transport, Mongo, and run artifact path write access).

## Scope
This preflight is intentionally lightweight and docs-first:
- Verifies local readiness signals only.
- Does **not** execute the scenario.
- Keeps checks reusable while a formal Java/Python automated harness is still evolving.

## Preflight Checklist
Run these checks in order:

1. **Scenario path exists**
   - Default: `examples/fednow-cam29-success.yaml`
2. **Scenario references expected FEDNOW plugins**
   - `applauncher` in lifecycle start
   - `transport-postman` in send step
   - `verify-mongo` in verify step
3. **AppLauncher is reachable**
   - Health URL should return HTTP 2xx/3xx
4. **Transport endpoint is reachable**
   - Health URL should return HTTP 2xx/3xx
5. **Mongo endpoint is reachable**
   - TCP port check to host/port (default `localhost:27017`)
6. **`runs/` path is writable**
   - Create/write/delete a preflight probe file

## Reusable PowerShell Script
Script location: `docs/scripts/fednow-preflight.ps1`

### Typical usage
```powershell
pwsh -File docs/scripts/fednow-preflight.ps1
```

### Usage with explicit endpoints
```powershell
pwsh -File docs/scripts/fednow-preflight.ps1 \
  -ScenarioPath examples/fednow-cam29-success.yaml \
  -AppLauncherHealthUrl http://localhost:8080/health \
  -TransportHealthUrl http://localhost:3000/health \
  -MongoHost localhost \
  -MongoPort 27017
```

### Pass/Fail
- **Pass**: script exits `0` and prints `FEDNOW preflight: PASS`.
- **Fail**: script exits `1` and prints each failed check.

### Troubleshooting note
- If health endpoints require auth/TLS, point the script at local dev readiness URLs (or pass custom `-AppLauncherHealthUrl` / `-TransportHealthUrl`) to avoid false fails.

## Recommended Run Sequence
1. Run preflight script.
2. If pass, execute FEDNOW run command with fixed run id.
3. Validate artifacts per `docs/FEDNOW_REGRESSION_TEST_PLAN.md`.
