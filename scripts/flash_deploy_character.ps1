# Deploy Flash character app via WSL — thin wrapper.
#   .\scripts\flash_deploy_character.ps1
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "flash_deploy_app.ps1") "character"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
