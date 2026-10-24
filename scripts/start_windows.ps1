# Start FinAlly via docker compose. Usage: scripts\start_windows.ps1 [-Build] [-NoOpen]
param(
    [switch]$Build,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$Url = 'http://localhost:8000'

if (-not (Test-Path '.env')) {
    Write-Host 'Note: no .env found; AI chat needs OPENROUTER_API_KEY (see .env.example).'
}

# Build when asked, or when the image has never been built
if (-not $Build) {
    docker image inspect finally:latest *> $null
    if ($LASTEXITCODE -ne 0) { $Build = $true }
}

if ($Build) {
    docker compose up -d --build
} else {
    docker compose up -d
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "FinAlly is running at $Url"

if (-not $NoOpen) {
    Start-Process $Url
}
