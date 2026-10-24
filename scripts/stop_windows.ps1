# Stop FinAlly. The finally-data volume is kept, so your portfolio persists.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

docker compose down
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'FinAlly stopped (data volume preserved).'
