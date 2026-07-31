# Deploy Flash character endpoint via WSL2 (Flash CLI is not native on Windows).
# Usage (from repo root):
#   .\scripts\flash_deploy_character.ps1
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
  Write-Error @"
WSL not found. Install WSL2 and a Linux distro (elevated PowerShell):
  wsl --install -d Ubuntu
Then reboot if prompted, open Ubuntu once, and re-run this script.
See docs/portal.md and https://docs.runpod.io/flash/windows-wsl2
"@
}

# WSL feature can be on with zero distros — flash cannot run until Ubuntu (etc.) exists.
$distroOut = & wsl -l -q 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($distroOut) -or ($distroOut -match "no installed distribution")) {
  Write-Error @"
WSL has no Linux distribution installed (Flash CLI needs Linux).
In an elevated PowerShell run:
  wsl --install -d Ubuntu
Reboot if prompted, open Ubuntu once to finish setup, then re-run:
  .\scripts\flash_deploy_character.ps1
See docs/portal.md
"@
}

# Convert Windows path to WSL (/mnt/<drive>/...)
$drive = $Root.Path.Substring(0, 1).ToLower()
$tail = $Root.Path.Substring(2).Replace("\", "/")
$wslRoot = "/mnt/$drive$tail"

Write-Host "WSL repo: $wslRoot"
$cmd = "cd '$wslRoot' && sed -i 's/\r$//' scripts/flash_deploy_character.sh && chmod +x scripts/flash_deploy_character.sh && bash scripts/flash_deploy_character.sh"
wsl -e bash -lc $cmd
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
