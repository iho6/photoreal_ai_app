# Stage-1: path preflight, prefer drive-local runtime/python, heal/create .venv,
# install [portal] if needed, start API, open browser when healthy.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
Set-Location $Root

$ApiHost = if ($env:PHOTOREAL_API_HOST) { $env:PHOTOREAL_API_HOST } else { "127.0.0.1" }
$ApiPort = if ($env:PHOTOREAL_API_PORT) { $env:PHOTOREAL_API_PORT } else { "8010" }
$Url = "http://${ApiHost}:${ApiPort}/"
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$PortableDir = Join-Path $Root "runtime\python"
$PortablePython = Join-Path $PortableDir "python.exe"
$Logs = Join-Path $Root "data\logs"
$MinPython = [version]"3.11"
$script:UsingPortablePython = $false

function Test-ApiHealth {
  try {
    $r = Invoke-WebRequest -Uri "http://${ApiHost}:${ApiPort}/api/health" -UseBasicParsing -TimeoutSec 2
    return $r.StatusCode -eq 200
  } catch {
    return $false
  }
}

function Get-RunningApiBuild {
  try {
    $r = Invoke-WebRequest -Uri "http://${ApiHost}:${ApiPort}/api/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -ne 200) { return $null }
    $obj = $r.Content | ConvertFrom-Json
    if ($obj -and $obj.build) { return [string]$obj.build }
  } catch {}
  return $null
}

function Get-ExpectedApiBuild {
  try {
    $out = & $VenvPython -c "from photoreal.portal.build_id import build_id; print(build_id())" 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return (($out | Select-Object -Last 1).ToString().Trim())
  } catch {
    return $null
  }
}

function Get-PathDrive([string]$Path) {
  if (-not $Path) { return $null }
  try {
    $full = [System.IO.Path]::GetFullPath($Path)
    if ($full.Length -ge 2 -and $full[1] -eq [char]':') {
      return $full.Substring(0, 1).ToUpperInvariant()
    }
  } catch {}
  return $null
}

function Test-PathUnder([string]$Child, [string]$Parent) {
  if (-not $Child -or -not $Parent) { return $false }
  try {
    $c = [System.IO.Path]::GetFullPath($Child).TrimEnd('\', '/').ToLowerInvariant()
    $p = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/').ToLowerInvariant()
    return ($c -eq $p) -or $c.StartsWith($p + [System.IO.Path]::DirectorySeparatorChar) -or
      $c.StartsWith($p + [System.IO.Path]::AltDirectorySeparatorChar)
  } catch {
    return $false
  }
}

function Test-PythonUsable([string]$Exe) {
  if (-not $Exe) { return $false }
  if (-not (Test-Path -LiteralPath $Exe)) { return $false }
  # Windows Store stub: Get-Command finds it, but it is not a real interpreter.
  if ($Exe -match '[\\/]WindowsApps[\\/]') { return $false }
  try {
    $out = & $Exe -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    $ver = [version](($out | Select-Object -Last 1).ToString().Trim())
    return $ver -ge $MinPython
  } catch {
    return $false
  }
}

# Native stderr + Stop + 2>&1 becomes terminating NativeCommandError; fail on exit code only.
# Pass native flags via -ArgumentList (do not use remaining-args; -e binds as PS params).
function Invoke-NativeHost {
  param(
    [Parameter(Mandatory = $true, Position = 0)][string]$FilePath,
    [Parameter(Position = 1)][string[]]$ArgumentList = @()
  )
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $FilePath @ArgumentList 2>&1 | ForEach-Object {
      if ($_ -is [System.Management.Automation.ErrorRecord]) {
        Write-Host $_.ToString()
      } else {
        Write-Host $_
      }
    }
  } finally {
    $ErrorActionPreference = $prev
  }
  if ($null -eq $LASTEXITCODE) { return }
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed (exit $LASTEXITCODE): $FilePath $($ArgumentList -join ' ')"
  }
}

function Ensure-PortablePython {
  $ensure = Join-Path $PSScriptRoot "ensure_portable_python.ps1"
  if (-not (Test-Path -LiteralPath $ensure)) {
    Write-Host "Preflight: ensure_portable_python.ps1 missing; skipping portable bootstrap"
    return $null
  }
  Write-Host "Preflight: ensuring drive-local Python under runtime\python ..."
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $lines = @()
  try {
    $lines = @(& $ensure -Root $Root 2>&1)
  } catch {
    Write-Host "Preflight: portable Python bootstrap threw: $($_.Exception.Message)"
    return $null
  } finally {
    $ErrorActionPreference = $prev
  }
  $pathOut = $null
  foreach ($line in $lines) {
    if ($line -is [System.Management.Automation.ErrorRecord]) {
      Write-Host $line.ToString()
    } else {
      Write-Host $line
      $pathOut = [string]$line
    }
  }
  if (Test-PythonUsable $PortablePython) {
    return [string]$PortablePython
  }
  if ($pathOut -and (Test-PythonUsable $pathOut)) {
    return [string]$pathOut
  }
  Write-Host "Preflight: portable Python bootstrap failed (unusable at $PortablePython)"
  return $null
}

function Resolve-SystemPython {
  # 1) py launcher
  $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
  if ($pyLauncher) {
    foreach ($arg in @("-3.11", "-3")) {
      Write-Host "Preflight: trying py $arg ..."
      try {
        $resolved = & py $arg -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) {
          $exe = ($resolved | Select-Object -Last 1).ToString().Trim()
          if ($exe -match '[\\/]WindowsApps[\\/]') {
            Write-Host "Preflight: skip WindowsApps stub -> $exe"
            continue
          }
          if (Test-PythonUsable $exe) {
            Write-Host "Preflight: accepted py $arg -> $exe"
            return $exe
          }
          Write-Host "Preflight: skip (version < $MinPython or unusable) -> $exe"
        } else {
          Write-Host "Preflight: py $arg not available"
        }
      } catch {
        Write-Host "Preflight: py $arg failed"
      }
    }
  } else {
    Write-Host "Preflight: py launcher not on PATH"
  }

  # 2) PATH python / python3 (skip WindowsApps stubs)
  Write-Host "Preflight: checking PATH for python / python3 ..."
  foreach ($name in @("python", "python3")) {
    $cmds = @(Get-Command $name -All -ErrorAction SilentlyContinue)
    foreach ($cmd in $cmds) {
      $exe = $cmd.Source
      if ($exe -match '[\\/]WindowsApps[\\/]') {
        Write-Host "Preflight: skip WindowsApps stub -> $exe"
        continue
      }
      # Prefer not to pick our own portable tree here (handled earlier).
      if (Test-PathUnder $exe $PortableDir) { continue }
      if (Test-PythonUsable $exe) {
        Write-Host "Preflight: accepted PATH $name -> $exe"
        return $exe
      }
      Write-Host "Preflight: skip (unusable or version < $MinPython) -> $exe"
    }
  }

  # 3) Common install roots
  Write-Host "Preflight: checking common install roots ..."
  $candidates = @()
  $local = Join-Path $env:LOCALAPPDATA "Programs\Python"
  if (Test-Path $local) {
    $candidates += Get-ChildItem -Path $local -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match 'Python3\d+' }
  }
  $candidates += Get-ChildItem -Path "C:\" -Filter "Python3*" -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "python.exe" } |
    Where-Object { Test-Path $_ } |
    ForEach-Object { Get-Item $_ }

  if ($candidates.Count -eq 0) {
    Write-Host "Preflight: no candidates under LocalAppData\Programs\Python or C:\Python3*"
  }
  foreach ($item in $candidates) {
    $exe = if ($item -is [string]) { $item } else { $item.FullName }
    if (Test-PythonUsable $exe) {
      Write-Host "Preflight: accepted install-root -> $exe"
      return $exe
    }
    Write-Host "Preflight: skip install-root (unusable) -> $exe"
  }

  Write-Host "Preflight: no usable system Python found in scan"
  return $null
}

function Refresh-ProcessPath {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ";"
}

function Ensure-HostPython {
  Write-Host "Preflight: preferring drive-local Python under runtime\python ..."
  $portable = Ensure-PortablePython
  if ($portable) {
    $script:UsingPortablePython = $true
    Write-Host "Preflight: host Python OK (portable) -> $portable"
    return [string]$portable
  }

  Write-Host "Preflight: portable Python unavailable; scanning system Python >= $MinPython ..."
  Write-Host "WARNING: system Python ties .venv to this machine (C:\Users\...)." -ForegroundColor Yellow
  Write-Host "WARNING: moving the drive will likely require recreating .venv." -ForegroundColor Yellow

  $hostPy = Resolve-SystemPython
  if ($hostPy) {
    $script:UsingPortablePython = $false
    Write-Host "Preflight: host Python OK (system) -> $hostPy"
    return [string]$hostPy
  }

  Write-Host "Preflight: no usable Python found; installing Python.Python.3.11 via winget ..."
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Error "python >= $MinPython not found and winget is unavailable. Install Python 3.11+ from https://www.python.org/downloads/ (Add to PATH), then re-run -- or fix network so runtime\python can download."
  }
  try {
    Invoke-NativeHost -FilePath winget -ArgumentList @('install', '-e', '--id', 'Python.Python.3.11', '--accept-package-agreements', '--accept-source-agreements')
  } catch {
    Write-Error "winget failed to install Python.Python.3.11. $($_.Exception.Message) Install Python 3.11+ manually, then re-run."
  }
  Refresh-ProcessPath
  Start-Sleep -Seconds 2
  $hostPy = Resolve-SystemPython
  if (-not $hostPy) {
    Write-Error "Python was installed but is not yet on PATH. Close this terminal, open a new one, and re-run .\launch.bat"
  }
  $script:UsingPortablePython = $false
  Write-Host "Preflight: host Python OK (system/winget) -> $hostPy"
  return [string]$hostPy
}

function Test-VenvHealthy {
  $script:VenvUnhealthyReason = $null
  if (-not (Test-Path -LiteralPath $VenvDir)) {
    $script:VenvUnhealthyReason = ".venv directory missing"
    return $false
  }
  if (-not (Test-Path -LiteralPath $VenvPython)) {
    $script:VenvUnhealthyReason = "missing Scripts\python.exe"
    return $false
  }

  $cfg = Join-Path $VenvDir "pyvenv.cfg"
  $homePath = $null
  $execPath = $null
  $commandLine = $null
  if (Test-Path -LiteralPath $cfg) {
    foreach ($line in Get-Content -LiteralPath $cfg) {
      if ($line -match '^\s*(home|executable|command)\s*=\s*(.+)\s*$') {
        $key = $Matches[1]
        $p = $Matches[2].Trim().Trim("'").Trim('"')
        if ($key -eq "home") { $homePath = $p }
        elseif ($key -eq "executable") { $execPath = $p }
        elseif ($key -eq "command") { $commandLine = $p }
      }
    }
  }

  if ($execPath) {
    if (-not (Test-Path -LiteralPath $execPath)) {
      $script:VenvUnhealthyReason = "pyvenv.cfg executable= path missing -> $execPath"
      return $false
    }
  }
  if ($homePath) {
    if (-not (Test-Path -LiteralPath $homePath) -and
        -not (Test-Path -LiteralPath (Join-Path $homePath "python.exe"))) {
      $script:VenvUnhealthyReason = "pyvenv.cfg home= path missing -> $homePath"
      return $false
    }
  }

  # Prefer .venv bound to drive-local runtime\python when that tree exists.
  if (Test-Path -LiteralPath $PortablePython) {
    $bound = $false
    if ($homePath -and (Test-PathUnder $homePath $PortableDir)) { $bound = $true }
    if ($execPath -and (Test-PathUnder $execPath $PortableDir)) { $bound = $true }
    if (-not $bound) {
      $script:VenvUnhealthyReason =
        "pyvenv.cfg home/executable not under runtime\python (migrate off system Python)"
      return $false
    }
  }

  # Drive-letter change: recorded -m venv path vs current repo root.
  # Avoid nested quotes / [char class] in -match patterns (PowerShell parse pitfalls).
  $rootDrive = Get-PathDrive $Root
  if ($commandLine -and $rootDrive) {
    $venvCreate = $null
    if ($commandLine -match '(?i)-m\s+venv\s+(.+)$') {
      $venvCreate = $Matches[1].Trim().Trim([char]34).Trim([char]39)
    }
    if ($venvCreate) {
      $createDrive = Get-PathDrive $venvCreate
      if ($createDrive -and ($createDrive -ne $rootDrive)) {
        $script:VenvUnhealthyReason =
          "pyvenv.cfg create drive $createDrive != repo drive $rootDrive"
        return $false
      }
    }
  }

  try {
    & $VenvPython --version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { return $true }
    $script:VenvUnhealthyReason = "venv python --version failed (exit $LASTEXITCODE)"
    return $false
  } catch {
    $script:VenvUnhealthyReason = "venv python --version raised: $($_.Exception.Message)"
    return $false
  }
}

function Ensure-Venv([string]$HostPython) {
  if (Test-VenvHealthy) {
    Write-Host "Preflight: .venv healthy"
    return
  }
  $reason = if ($script:VenvUnhealthyReason) { $script:VenvUnhealthyReason } else { "unknown" }
  Write-Host "Preflight: .venv unhealthy: $reason"
  if (Test-Path -LiteralPath $VenvDir) {
    Write-Host "Preflight: removing .venv ..."
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
  }
  Write-Host "Preflight: creating .venv with $HostPython ..."
  & $HostPython -m venv $VenvDir
  if (-not (Test-VenvHealthy)) {
    $failReason = if ($script:VenvUnhealthyReason) { $script:VenvUnhealthyReason } else { "unknown" }
    Write-Error "Failed to create a working .venv with $HostPython ($failReason)"
  }
  Write-Host "Preflight: .venv recreated OK"
}

function Test-PortalDeps {
  # Keep in sync with photoreal.portal.install_probe.PORTAL_MODULES (incl. nacl/pynacl).
  & $VenvPython -c @"
try:
    from photoreal.portal.install_probe import portal_deps_satisfied
    raise SystemExit(0 if portal_deps_satisfied() else 1)
except Exception:
    import importlib.util
    for m in ('fastapi', 'uvicorn', 'dotenv', 'httpx', 'nacl'):
        if importlib.util.find_spec(m) is None:
            raise SystemExit(1)
    raise SystemExit(0)
"@
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

$HostPython = [string](Ensure-HostPython | Select-Object -Last 1)
if (-not $HostPython -or -not (Test-Path -LiteralPath $HostPython)) {
  Write-Error "Preflight: resolved host Python path is invalid: '$HostPython'"
}
Ensure-Venv $HostPython

if (-not (Test-PortalDeps)) {
  Write-Host "Installing portal deps ..."
  try {
    Invoke-NativeHost -FilePath $VenvPython -ArgumentList @('-m', 'pip', 'install', '-U', 'pip', 'setuptools', 'wheel')
    Invoke-NativeHost -FilePath $VenvPython -ArgumentList @('-m', 'pip', 'install', '-e', '.[portal]')
  } catch {
    Write-Error "Failed to install portal deps: $($_.Exception.Message)"
  }
} else {
  Write-Host "skip (already installed): portal deps"
}

New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$apiOut = Join-Path $Logs "api.out.log"
$apiErr = Join-Path $Logs "api.err.log"

$needStart = $true
if (Test-ApiHealth) {
  $runningBuild = Get-RunningApiBuild
  $expectedBuild = Get-ExpectedApiBuild
  if ($runningBuild -and $expectedBuild -and ($runningBuild -eq $expectedBuild)) {
    Write-Host "API already healthy on $Url (build $runningBuild)"
    $needStart = $false
  } else {
    Write-Host "Preflight: portal API is stale (code changed) -- restarting"
    if (-not $runningBuild) {
      Write-Host "Preflight: running API has no build fingerprint (predates persistence)"
    } elseif (-not $expectedBuild) {
      Write-Host "Preflight: could not compute expected build_id from venv"
    } else {
      Write-Host "Preflight: running=$runningBuild expected=$expectedBuild"
    }
  }
}

if ($needStart) {
  Stop-PortListeners ([int]$ApiPort)
  $argList = @("-m", "photoreal.portal", "--host", $ApiHost, "--port", $ApiPort)
  Start-Process -FilePath $VenvPython -ArgumentList $argList `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $apiOut `
    -RedirectStandardError $apiErr `
    -WindowStyle Hidden
}

for ($i = 0; $i -lt 40; $i++) {
  if (Test-ApiHealth) { break }
  Start-Sleep -Milliseconds 300
}

if (-not (Test-ApiHealth)) {
  Write-Host "ERROR: portal API did not become healthy at $Url" -ForegroundColor Red
  Write-Host "API logs: $apiOut / $apiErr"
  if (Test-Path -LiteralPath $apiErr) {
    Write-Host "--- api.err.log (tail) ---"
    Get-Content -LiteralPath $apiErr -Tail 40
  }
  exit 1
}

$openBuild = Get-RunningApiBuild
$openUrl = $Url
if ($openBuild) {
  $openUrl = "${Url}?b=$openBuild"
}
Start-Process $openUrl
Write-Host "Portal: $openUrl"
Write-Host "API logs: $apiOut / $apiErr"
if ($script:UsingPortablePython) {
  Write-Host "Python: drive-local runtime\python (keep this volume drive letter stable when moving PCs)."
} else {
  Write-Host "Python: system interpreter (venv is machine-tied)."
}
Write-Host "Fill credentials in the UI, then click Launch (installs weights + starts Comfy)."
