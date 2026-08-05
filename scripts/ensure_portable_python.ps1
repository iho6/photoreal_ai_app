# Ensure a relocatable CPython lives under <repo>/runtime/python (Windows x64).
# Used by Stage-1 so .venv is not tied to each machine's C:\Users\...\Python.
#
# Usage:
#   .\scripts\ensure_portable_python.ps1
#   .\scripts\ensure_portable_python.ps1 -Root "H:\path\to\photoreal_ai_app"
#
# Returns the path to runtime\python\python.exe on success (stdout last line).

param(
  [string]$Root = ""
)

$ErrorActionPreference = "Stop"
$MinPython = [version]"3.11"
# Full Windows x64 build on NuGet (supports python -m venv); not the embeddable zip.
$PythonNuGetVersion = "3.11.9"
$PythonNuGetUrl = "https://globalcdn.nuget.org/packages/python.$PythonNuGetVersion.nupkg"

if (-not $Root) {
  $Root = Split-Path -Parent $PSScriptRoot
  if (-not $Root) {
    $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
  }
}
$Root = (Resolve-Path -LiteralPath $Root).Path
$PortableDir = Join-Path $Root "runtime\python"
$PortablePython = Join-Path $PortableDir "python.exe"

function Test-PythonUsable([string]$Exe) {
  if (-not $Exe) { return $false }
  if (-not (Test-Path -LiteralPath $Exe)) { return $false }
  if ($Exe -match '[\\/]WindowsApps[\\/]') { return $false }
  try {
    $out = & $Exe -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    $ver = [version](($out | Select-Object -Last 1).ToString().Trim())
    if ($ver -lt $MinPython) { return $false }
    # Must support venv for Stage-1.
    & $Exe -c "import venv" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

# Native stderr + $ErrorActionPreference Stop + 2>&1 becomes terminating NativeCommandError.
# Print all streams as text; fail only on non-zero exit code.
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

function Install-PortablePython {
  Write-Host "Portable Python: installing $PythonNuGetVersion into $PortableDir ..."
  $staging = Join-Path $env:TEMP ("photoreal-python-" + [guid]::NewGuid().ToString("n"))
  $nupkg = Join-Path $staging "python.nupkg"
  $extract = Join-Path $staging "extract"
  New-Item -ItemType Directory -Force -Path $staging, $extract | Out-Null
  try {
    Write-Host "Portable Python: downloading $PythonNuGetUrl ..."
    Invoke-WebRequest -Uri $PythonNuGetUrl -OutFile $nupkg -UseBasicParsing
    # .nupkg is a zip; Expand-Archive only accepts .zip extension
    $zip = Join-Path $staging "python.zip"
    Move-Item -LiteralPath $nupkg -Destination $zip -Force
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
    $tools = Join-Path $extract "tools"
    if (-not (Test-Path -LiteralPath (Join-Path $tools "python.exe"))) {
      throw "NuGet package missing tools\python.exe"
    }
    if (Test-Path -LiteralPath $PortableDir) {
      Write-Host "Portable Python: removing incomplete $PortableDir ..."
      Remove-Item -LiteralPath $PortableDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $PortableDir) | Out-Null
    Move-Item -LiteralPath $tools -Destination $PortableDir
    # Ensure pip is available (NuGet builds usually ship ensurepip).
    & $PortablePython -m ensurepip --upgrade 2>$null | Out-Null
    Invoke-NativeHost -FilePath $PortablePython -ArgumentList @('-m', 'pip', 'install', '-U', 'pip', 'setuptools', 'wheel')
  } finally {
    if (Test-Path -LiteralPath $staging) {
      Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
  }
}

if (Test-PythonUsable $PortablePython) {
  Write-Host "Portable Python: OK -> $PortablePython"
  Write-Output $PortablePython
  return
}

if (Test-Path -LiteralPath $PortableDir) {
  Write-Host "Portable Python: present but unusable; reinstalling ..."
  Remove-Item -LiteralPath $PortableDir -Recurse -Force
}

Install-PortablePython

if (-not (Test-PythonUsable $PortablePython)) {
  Write-Error "Portable Python install failed or is unusable at $PortablePython"
}

Write-Host "Portable Python: installed OK -> $PortablePython"
Write-Output $PortablePython
return