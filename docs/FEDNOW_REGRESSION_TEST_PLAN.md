# FEDNOW Regression Test Plan (Docs-Only, Pre-`src/test`)

## Purpose
This plan defines a tight, repeatable FEDNOW-only regression checklist that can be run manually from repo root until a formal `src/test` harness is introduced.

## Scope
In scope:
- FEDNOW scenario parsing for `scenarios/fednow/cam29/scenario.yaml`.
- Deterministic evidence generation in `runs/<run-id>/`.
- Reused run-directory behavior when unrelated files already exist (including lock-style simulation).

Out of scope:
- Non-FEDNOW scenarios.
- End-to-end plugin execution wiring (`transport-postman`, `verify-mongo`, `applauncher`).
- Broader CLI UX/security checks not tied to FEDNOW regressions.

## Regression Targets
1. Parser accepts the FEDNOW scenario shape currently used by CAM29.
2. Run succeeds with a fixed run id.
3. Required managed artifacts are (re)written:
   - `scenario.yaml`
   - `summary.json`
   - `events.log`
   - `manifest.json`
4. Reusing `runs/<run-id>` does not fail when an unrelated extra file exists.
5. Reusing `runs/<run-id>` does not fail when that unrelated file is held with an exclusive lock simulation.

## Preconditions
- JDK is available: `javac -version`, `java -version`.
- Shell cwd is repository root.
- `scenarios/fednow/cam29/scenario.yaml` exists.

## Test Matrix (Minimal)
| ID | Check | Expected |
|---|---|---|
| FDN-001 | Compile Java sources under `src/main/java/continuum` | Compile succeeds |
| FDN-002 | Run CAM29 with fixed `runId` | Exit code `0`; scenario + run directory printed |
| FDN-003 | Validate required artifacts exist | All four managed artifacts present |
| FDN-004 | Reuse run dir with unrelated existing file | Exit code `0`; unrelated file preserved |
| FDN-005 | Reuse run dir with unrelated locked file simulation | Exit code `0`; unrelated file preserved |

## Execution Commands (PowerShell)
```powershell
# FDN-001: compile
$classesDir = Join-Path (Resolve-Path .tmp).Path "classes-fednow-regression"
New-Item -ItemType Directory -Force -Path $classesDir | Out-Null
$sources = Get-ChildItem -Recurse -File src/main/java/continuum | Where-Object { $_.Extension -eq ".java" }
javac -d $classesDir ($sources | ForEach-Object { $_.FullName })

# FDN-002: fixed run-id smoke
$runId = "run-fednow-regression-001"
java "-Dcontinuum.runId=$runId" -cp $classesDir continuum.cli.ContinuumCli run scenarios/fednow/cam29/scenario.yaml

# FDN-003: artifact presence
$runDir = Join-Path (Resolve-Path runs).Path $runId
Get-Item (Join-Path $runDir "scenario.yaml") | Out-Null
Get-Item (Join-Path $runDir "summary.json") | Out-Null
Get-Item (Join-Path $runDir "events.log") | Out-Null
Get-Item (Join-Path $runDir "manifest.json") | Out-Null

# FDN-004: reuse run directory with unrelated file
$reuseRunId = "run-fednow-regression-reuse"
$reuseDir = Join-Path (Resolve-Path runs).Path $reuseRunId
New-Item -ItemType Directory -Force -Path $reuseDir | Out-Null
Set-Content -Path (Join-Path $reuseDir "debug.tmp") -Value "unrelated" -Encoding UTF8
java "-Dcontinuum.runId=$reuseRunId" -cp $classesDir continuum.cli.ContinuumCli run scenarios/fednow/cam29/scenario.yaml
Get-Content (Join-Path $reuseDir "debug.tmp") | Out-Null

# FDN-005: lock simulation on unrelated file
$lockRunId = "run-fednow-regression-lock"
$lockDir = Join-Path (Resolve-Path runs).Path $lockRunId
New-Item -ItemType Directory -Force -Path $lockDir | Out-Null
$lockPath = Join-Path $lockDir "debug.tmp"
Set-Content -Path $lockPath -Value "locked" -Encoding UTF8
$fs = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::None)
try {
  java "-Dcontinuum.runId=$lockRunId" -cp $classesDir continuum.cli.ContinuumCli run scenarios/fednow/cam29/scenario.yaml
} finally {
  $fs.Close()
  $fs.Dispose()
}
Get-Content $lockPath | Out-Null
```

## Pass/Fail Criteria
Pass if all are true:
- FDN-001..FDN-005 complete without command failure.
- CLI output contains `Scenario: fednow-cam29-skeleton`.
- CLI output contains `Run directory:` pointing to the chosen run id.
- `debug.tmp` remains present for reuse/lock checks.

Fail on any of:
- Parser/CLI crash or non-zero exit where success is expected.
- Missing managed artifacts.
- Reuse/lock checks fail due to unrelated extra file handling.

## Evidence to Attach in Ticket/PR
- Terminal output snippets for FDN-002, FDN-004, FDN-005.
- `Get-ChildItem runs/<run-id>` output for at least one successful run.
- Commit IDs associated with the FEDNOW fix and follow-on hardening.

## Cleanup (Optional)
```powershell
Remove-Item -Recurse -Force .tmp/classes-fednow-regression -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force runs/run-fednow-regression-001 -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force runs/run-fednow-regression-reuse -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force runs/run-fednow-regression-lock -ErrorAction SilentlyContinue
```

## Future Migration to Automated Tests
When `src/test` is available, convert this plan into:
- Parser unit tests for FEDNOW YAML shape handling.
- File evidence collector tests for run-dir reuse behavior.
- Integration test invoking CLI run path with fixed run ids and artifact assertions.
