# FEDNOW Local Run Guide (Java CLI Path)

## Scope
This guide is for local FEDNOW CAM29 scenario runs using:
- Scenario: `scenarios/fednow/cam29/scenario.yaml`
- CLI entry: `src/main/java/continuum/cli/ContinuumCli.java`
- Evidence output: `runs/<run-id>/`

## What Was Fixed
- The evidence collector no longer recursively clears the entire existing `runs/<run-id>` directory at run start.
- Why it failed before: on Windows, any locked leftover file in a reused run directory caused initialization to fail before `scenario.yaml`, `summary.json`, `events.log`, and `manifest.json` were written.
- Current behavior: run directory is reused as-is, and managed artifacts are overwritten deterministically.

## Quick Start (FEDNOW Local)
Run from repository root in PowerShell:

```powershell
$classesDir = Join-Path (Resolve-Path .tmp).Path "classes-fednow"
New-Item -ItemType Directory -Force -Path $classesDir | Out-Null
$sources = Get-ChildItem -Recurse -File src/main/java/continuum | Where-Object { $_.Extension -eq ".java" }
javac -d $classesDir ($sources | ForEach-Object { $_.FullName })

java "-Dcontinuum.runId=run-fednow-smoke" -cp $classesDir continuum.cli.ContinuumCli run scenarios/fednow/cam29/scenario.yaml
```

Expected success output includes:
- `Scenario: fednow-cam29-skeleton`
- `Run directory: <repo>\runs\run-fednow-smoke`

## Troubleshooting (Windows + Path + Maven/JDK)
- JDK missing:
  - `javac -version`
  - `java -version`
- Wrong Java on PATH:
  - set `JAVA_HOME` to your JDK and restart shell.
- Spaces in path:
  - use variables as shown above (`$classesDir`) instead of hardcoding classpath strings.
- Reused run directory with locked files:
  - unrelated locked files should no longer block run initialization.
  - if one of the managed artifacts (`scenario.yaml`, `summary.json`, `events.log`, `manifest.json`) is locked, writes can still fail; close the locking process or use a different `runId`.
- Maven note:
  - this repo root does not currently contain `pom.xml`.
  - use the `javac` commands above for this path; if you run from another Maven wrapper project, ensure Maven uses the same JDK (`JAVA_HOME`) as `javac`.

## Evidence Artifacts Guide
For each run under `runs/<run-id>/`:
- `scenario.yaml`: snapshot of the input scenario file used for execution.
- `summary.json`: run metadata/status emitted by CLI.
- `events.log`: step event log (may be empty for the current skeleton scenario path).
- `manifest.json`: declared artifact list for deterministic evidence output.

Notes:
- Artifact names and formats are unchanged by this fix.
- Extra files already present in the run directory are not removed by initialization.

## Test/Validation Notes
Commands used to validate this fix:

```powershell
$classesDir = Join-Path (Resolve-Path .tmp).Path "classes-fednow-fix"
New-Item -ItemType Directory -Force -Path $classesDir | Out-Null
$sources = Get-ChildItem -Recurse -File src/main/java/continuum | Where-Object { $_.Extension -eq ".java" }
javac -d $classesDir ($sources | ForEach-Object { $_.FullName })

java "-Dcontinuum.runId=run-fednow-fix-smoke" -cp $classesDir continuum.cli.ContinuumCli run scenarios/fednow/cam29/scenario.yaml
```

Windows lock/reuse check (same run directory with an unrelated locked file):

```powershell
$runId = "run-fednow-lock-unrelated"
$runDir = Join-Path (Resolve-Path runs).Path $runId
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$lockPath = Join-Path $runDir "debug.tmp"
Set-Content -Path $lockPath -Value "locked artifact from external tool" -Encoding UTF8
$fs = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::None)
try {
  java "-Dcontinuum.runId=$runId" -cp $classesDir continuum.cli.ContinuumCli run scenarios/fednow/cam29/scenario.yaml
} finally {
  $fs.Close()
  $fs.Dispose()
}
```

Observed result after fix:
- CLI returns success.
- `runs/run-fednow-lock-unrelated/` contains managed artifacts plus `debug.tmp`.

## Known Limitations / Assumptions
- This fix targets initialization failures from recursive directory cleanup on reused run directories.
- If a managed artifact file is itself locked at write time, the run can still fail.
- This guide covers the Java CLI FEDNOW path only; it does not change Python CLI behavior.
