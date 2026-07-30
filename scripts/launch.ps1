# Stage-1: create .venv, install [portal] if needed, start API (detached), open browser.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
Set-Location $Root

$ApiHost = if ($env:PHOTOREAL_API_HOST) { $env:PHOTOREAL_API_HOST } else { "127.0.0.1" }
$ApiPort = if ($env:PHOTOREAL_API_PORT) { $env:PHOTOREAL_API_PORT } else { "8010" }
$Url = "http://${ApiHost}:${ApiPort}/"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Logs = Join-Path $Root "data\logs"

function Test-ApiHealth {
  try {
    $r = Invoke-WebRequest -Uri "http://${ApiHost}:${ApiPort}/api/health" -UseBasicParsing -TimeoutSec 2
    return $r.StatusCode -eq 200
  } catch {
    return $false
  }
}

function Test-PortalDeps {
  & $VenvPython -c "import fastapi; import uvicorn; import dotenv" 2>$null
  return ($LASTEXITCODE -eq 0)
}

function Stop-PortListeners([int]$Port) {
  $lines = netstat -ano -p tcp 2>$null | Select-String -Pattern ":$Port\s+.+\s+LISTENING\s+(\d+)"
  foreach ($m in $lines) {
    if ($m -match "LISTENING\s+(\d+)\s*$") {
      $pidVal = [int]$Matches[1]
      if ($pidVal -gt 0) {
        Write-Host "Killing stale PID $pidVal on port $Port"
        taskkill /PID $pidVal /F 2>$null | Out-Null
      }
    }
  }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Error "python not found on PATH"
}

if (-not (Test-Path (Join-Path $Root ".venv"))) {
  Write-Host "Creating .venv ..."
  python -m venv (Join-Path $Root ".venv")
}

if (-not (Test-PortalDeps)) {
  Write-Host "Installing portal deps ..."
  & $VenvPython -m pip install -U pip setuptools wheel
  & $VenvPython -m pip install -e ".[portal]"
} else {
  Write-Host "skip (already installed): portal deps"
}

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

if (-not (Test-ApiHealth)) {
  Stop-PortListeners ([int]$ApiPort)
  $apiOut = Join-Path $Logs "api.out.log"
  $apiErr = Join-Path $Logs "api.err.log"
  $argList = @("-m", "photoreal.portal", "--host", $ApiHost, "--port", $ApiPort)
  Start-Process -FilePath $VenvPython -ArgumentList $argList `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $apiOut `
    -RedirectStandardError $apiErr `
    -WindowStyle Hidden
} else {
  Write-Host "API already healthy on $Url"
}

for ($i = 0; $i -lt 40; $i++) {
  if (Test-ApiHealth) { break }
  Start-Sleep -Milliseconds 300
}

Start-Process $Url
Write-Host "Portal: $Url"
Write-Host "API logs: $(Join-Path $Logs 'api.out.log') / $(Join-Path $Logs 'api.err.log')"
Write-Host "Fill credentials in the UI, then click Launch (installs weights + starts Comfy)."
