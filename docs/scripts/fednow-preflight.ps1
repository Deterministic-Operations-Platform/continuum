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
Set-StrictMode -Version Latest
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
    $exceptionMessage = $_.Exception.Message
    if ($_.Exception.InnerException) {
      $exceptionMessage = "$exceptionMessage | Inner: $($_.Exception.InnerException.Message)"
    }

    Add-Failure "$name unreachable at $url ($exceptionMessage)"
  }
}

function Test-MongoTcp([string]$host, [int]$port) {
  if (Get-Command -Name Test-NetConnection -ErrorAction SilentlyContinue) {
    $tcp = Test-NetConnection -ComputerName $host -Port $port -WarningAction SilentlyContinue
    return [bool]$tcp.TcpTestSucceeded
  }

  $tcpClient = [System.Net.Sockets.TcpClient]::new()
  try {
    $connectTask = $tcpClient.ConnectAsync($host, $port)
    $connectedInTime = $connectTask.Wait([TimeSpan]::FromSeconds($TimeoutSec))
    return ($connectedInTime -and $tcpClient.Connected)
  } finally {
    $tcpClient.Dispose()
  }
}

function Test-ScenarioPlugin([string]$scenarioText, [string]$name, [string]$pattern) {
  if ($scenarioText -match $pattern) {
    Add-Pass "Scenario references plugin: $name"
  } else {
    Add-Failure "Scenario does not reference plugin: $name"
  }
}

Write-Host "FEDNOW preflight starting..." -ForegroundColor Cyan

if (Test-Path -Path $ScenarioPath -PathType Leaf) {
  Add-Pass "Scenario file exists: $ScenarioPath"
} else {
  Add-Failure "Scenario file missing: $ScenarioPath"
}

if (Test-Path -Path $ScenarioPath -PathType Leaf) {
  Add-Pass "Scanning scenario for plugin references: $ScenarioPath"
  $scenarioText = Get-Content -Path $ScenarioPath -Raw
  Test-ScenarioPlugin -scenarioText $scenarioText -name "applauncher" -pattern '(?im)^\s*(plugin|name|type)\s*:\s*["'"'"']?applauncher["'"'"']?\s*$'
  Test-ScenarioPlugin -scenarioText $scenarioText -name "transport-postman" -pattern '(?im)^\s*(plugin|name|type)\s*:\s*["'"'"']?transport-postman["'"'"']?\s*$'
  Test-ScenarioPlugin -scenarioText $scenarioText -name "verify-mongo" -pattern '(?im)^\s*(plugin|name|type)\s*:\s*["'"'"']?verify-mongo["'"'"']?\s*$'
}

Test-Http -name "AppLauncher" -url $AppLauncherHealthUrl
Test-Http -name "Transport" -url $TransportHealthUrl

try {
  if (Test-MongoTcp -host $MongoHost -port $MongoPort) {
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

  $probeDir = Join-Path $runsRoot.Path ("preflight-probe-{0}-{1}" -f $PID, (Get-Date -Format "yyyyMMddHHmmssfff"))
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
