[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$docker = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
$envPath = Join-Path $projectRoot ".env.local"
$credentialsPath = Join-Path $projectRoot ".local-test-credentials.json"

if (-not (Test-Path -LiteralPath $docker)) {
    throw "Docker CLI nije pronađen. Pokrenite Docker Desktop pa pokušajte ponovo."
}
$env:PATH = "$(Split-Path $docker);$env:PATH"
if (-not (Test-Path -LiteralPath $envPath)) {
    & (Join-Path $PSScriptRoot "Initialize-LocalEnvironment.ps1")
}

Push-Location $projectRoot
try {
    & $docker compose --env-file .env.local -f compose.local.yaml up --build -d
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose pokretanje nije uspelo." }

    $healthy = $false
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "http://localhost:18080/health/live" -TimeoutSec 3
            if ($health.status -eq "ok") { $healthy = $true; break }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $healthy) {
        & $docker compose --env-file .env.local -f compose.local.yaml ps
        & $docker compose --env-file .env.local -f compose.local.yaml logs --tail 100 app
        throw "Aplikacija nije postala dostupna u očekivanom roku."
    }

    $credentials = Get-Content -LiteralPath $credentialsPath -Raw | ConvertFrom-Json
    $bootstrap = @{
        organization_name = "Lokalna test firma"
        tax_id = "999999999"
        registration_number = "99999999"
        admin_name = "Lokalni administrator"
        admin_email = $credentials.email
        password = $credentials.password
    } | ConvertTo-Json

    try {
        $token = Invoke-RestMethod -Uri "http://localhost:18080/api/v1/auth/bootstrap" -Method Post -ContentType "application/json" -Body $bootstrap
    } catch {
        if ($_.Exception.Response.StatusCode -ne [System.Net.HttpStatusCode]::Conflict) { throw }
        $login = @{ email = $credentials.email; password = $credentials.password } | ConvertTo-Json
        $token = Invoke-RestMethod -Uri "http://localhost:18080/api/v1/auth/login" -Method Post -ContentType "application/json" -Body $login
    }

    $headers = @{ Authorization = "Bearer $($token.access_token)" }
    $organizations = Invoke-RestMethod -Uri "http://localhost:18080/api/v1/organizations" -Headers $headers
    if (@($organizations).Count -lt 1) { throw "Test korisnik nema lokalnu firmu." }

    Write-Output "LOCAL_TEST_READY"
    Write-Output "Aplikacija: http://localhost:18080"
    Write-Output "Test email sanduče: http://localhost:18025"
    Write-Output "Korisnik: $($credentials.email)"
    Write-Output "Lozinka je sačuvana u .local-test-credentials.json (nije u Git-u)."
} finally {
    Pop-Location
}
