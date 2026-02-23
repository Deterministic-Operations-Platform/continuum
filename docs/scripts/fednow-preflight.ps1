param(
  [string]$ScenarioPath = "examples/fednow-cam29-success.yaml",
  [string]$RunsPath = "runs",
  [string]$AppLauncherHealthUrl = "http://localhost:8080/health",
  [string]$TransportHealthUrl = "http://localhost:3000/health",
  [string]$MongoHost = "localhost",
  [int]$MongoPort = 27017,
  [int]$TimeoutSec = 5
)

$ErrorActionPreference = "Stop"
$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure([string]$message) {
  $script:failures.Add($message) | Out-Null
  Write-Host "FAIL: $message" -ForegroundColor Red
}

function Add-Pass([string]$message) {
  Write-Host "PASS: $message" -ForegroundColor Green
}

function Test-Http([string]$name, [string]$url) {
  try {
    $response = Invoke-WebRequest -Uri $url -Method Get -TimeoutSec $TimeoutSec -UseBasicParsing
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
      Add-Pass "$name reachable ($url -> HTTP $($response.StatusCode))"
    } else {
      Add-Failure "$name returned non-ready status ($url -> HTTP $($response.StatusCode))"
    }
  } catch {
    Add-Failure "$name unreachable at $url ($($_.Exception.Message))"
  }
}

Write-Host "FEDNOW preflight starting..." -ForegroundColor Cyan

if (Test-Path -Path $ScenarioPath -PathType Leaf) {
  Add-Pass "Scenario file exists: $ScenarioPath"
} else {
  Add-Failure "Scenario file missing: $ScenarioPath"
}

if (Test-Path -Path $ScenarioPath -PathType Leaf) {
  $scenarioText = Get-Content -Path $ScenarioPath -Raw
  if ($scenarioText -match "applauncher") {
    Add-Pass "Scenario references lifecycle plugin: applauncher"
  } else {
    Add-Failure "Scenario does not reference applauncher"
  }

  if ($scenarioText -match "transport-postman") {
    Add-Pass "Scenario references transport plugin: transport-postman"
  } else {
    Add-Failure "Scenario does not reference transport-postman"
  }

  if ($scenarioText -match "verify-mongo") {
    Add-Pass "Scenario references verify plugin: verify-mongo"
  } else {
    Add-Failure "Scenario does not reference verify-mongo"
  }
}

Test-Http -name "AppLauncher" -url $AppLauncherHealthUrl
Test-Http -name "Transport" -url $TransportHealthUrl

try {
  $tcp = Test-NetConnection -ComputerName $MongoHost -Port $MongoPort -WarningAction SilentlyContinue
  if ($tcp.TcpTestSucceeded) {
    Add-Pass "Mongo reachable ($MongoHost:$MongoPort)"
  } else {
    Add-Failure "Mongo not reachable ($MongoHost:$MongoPort)"
  }
} catch {
  Add-Failure "Mongo check failed for $MongoHost:$MongoPort ($($_.Exception.Message))"
}

try {
  $runsRoot = Resolve-Path -Path $RunsPath -ErrorAction SilentlyContinue
  if (-not $runsRoot) {
    New-Item -ItemType Directory -Force -Path $RunsPath | Out-Null
    $runsRoot = Resolve-Path -Path $RunsPath
  }

  $probeDir = Join-Path $runsRoot.Path "preflight-probe"
  New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
  $probeFile = Join-Path $probeDir "write-test.txt"
  Set-Content -Path $probeFile -Value "ok" -Encoding UTF8
  Remove-Item -Recurse -Force $probeDir
  Add-Pass "Runs path writable: $RunsPath"
} catch {
  Add-Failure "Runs path is not writable: $RunsPath ($($_.Exception.Message))"
}

if ($failures.Count -eq 0) {
  Write-Host "FEDNOW preflight: PASS" -ForegroundColor Green
  exit 0
}

Write-Host "FEDNOW preflight: FAIL ($($failures.Count) check(s))" -ForegroundColor Red
$failures | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
exit 1
