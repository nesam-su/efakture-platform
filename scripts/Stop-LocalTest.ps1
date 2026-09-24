[CmdletBinding()]
param([switch]$ResetData)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$docker = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
$env:PATH = "$(Split-Path $docker);$env:PATH"

Push-Location $projectRoot
try {
    $arguments = @("compose", "--env-file", ".env.local", "-f", "compose.local.yaml", "down")
    if ($ResetData) { $arguments += "--volumes" }
    & $docker @arguments
    if ($LASTEXITCODE -ne 0) { throw "Zaustavljanje lokalnog okruženja nije uspelo." }
} finally {
    Pop-Location
}
