# Deploy Flash character app via WSL2 (Flash CLI is not native on Windows).
# Usage (from repo root):
#   .\scripts\flash_deploy_character.ps1
#   .\scripts\flash_deploy_app.ps1 character
$ErrorActionPreference = "Stop"

$AppId = if ($args.Count -ge 1) { $args[0] } else { "character" }
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
  Write-Error @"
WSL not found. Install WSL2 and a Linux distro (elevated PowerShell):
  wsl --install -d Ubuntu
Then reboot if prompted, open Ubuntu once, and re-run this script.
See docs/portal.md and https://docs.runpod.io/flash/windows-wsl2
"@
}

$distroOut = & wsl -l -q 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($distroOut) -or ($distroOut -match "no installed distribution")) {
  Write-Error @"
WSL has no Linux distribution installed (Flash CLI needs Linux).
In an elevated PowerShell run:
  wsl --install -d Ubuntu
Reboot if prompted, open Ubuntu once to finish setup, then re-run:
  .\scripts\flash_deploy_app.ps1 $AppId
See docs/portal.md
"@
}

$drive = $Root.Path.Substring(0, 1).ToLower()
$tail = $Root.Path.Substring(2).Replace("\", "/")
$wslRoot = "/mnt/$drive$tail"

Write-Host "WSL repo: $wslRoot app=$AppId"
$cmd = "cd '$wslRoot' && sed -i 's/\r$//' scripts/flash_deploy_app.sh && chmod +x scripts/flash_deploy_app.sh scripts/flash_deploy_character.sh && bash scripts/flash_deploy_app.sh '$AppId'"
wsl -e bash -lc $cmd
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
