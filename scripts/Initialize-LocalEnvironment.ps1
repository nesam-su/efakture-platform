[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot ".env.local"
$credentialsPath = Join-Path $projectRoot ".local-test-credentials.json"
$localAdminEmail = "admin@efakture.rs"

function New-RandomBytes([int]$Length) {
    $bytes = [byte[]]::new($Length)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return $bytes
}

function ConvertTo-Base64Url([byte[]]$Bytes, [bool]$TrimPadding) {
    $value = [Convert]::ToBase64String($Bytes).Replace("+", "-").Replace("/", "_")
    if ($TrimPadding) { return $value.TrimEnd("=") }
    return $value
}

function Initialize-LocalCertificate {
    $certificate = Get-ChildItem Cert:\CurrentUser\Root,Cert:\LocalMachine\Root -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -like "*CN=Avast Web/Mail Shield Root*" } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
    if (-not $certificate) { return "Dockerfile" }

    $certificateDirectory = Join-Path $projectRoot ".docker-local"
    [IO.Directory]::CreateDirectory($certificateDirectory) | Out-Null
    $raw = $certificate.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
    $base64 = [Convert]::ToBase64String($raw)
    $lines = [regex]::Matches($base64, ".{1,64}") | ForEach-Object { $_.Value }
    $pem = "-----BEGIN CERTIFICATE-----`n$($lines -join "`n")`n-----END CERTIFICATE-----`n"
    [IO.File]::WriteAllText(
        (Join-Path $certificateDirectory "avast-root.crt"),
        $pem,
        [Text.UTF8Encoding]::new($false)
    )
    return "Dockerfile.local"
}

$localDockerfile = Initialize-LocalCertificate

function Set-LocalCredentialEmail {
    if (-not (Test-Path -LiteralPath $credentialsPath)) { return }
    $credentials = [IO.File]::ReadAllText($credentialsPath) | ConvertFrom-Json
    if ($credentials.email -eq $localAdminEmail) { return }
    $updated = @{ email = $localAdminEmail; password = $credentials.password } | ConvertTo-Json
    [IO.File]::WriteAllText($credentialsPath, $updated, [Text.UTF8Encoding]::new($false))
}

function Set-LocalDockerfileSetting {
    if (-not (Test-Path -LiteralPath $envPath)) { return }
    $content = [IO.File]::ReadAllText($envPath)
    $content = [regex]::Replace(
        $content,
        "(?<![\r\n])LOCAL_DOCKERFILE=",
        "`nLOCAL_DOCKERFILE="
    )
    if ($content -match "(?m)^LOCAL_DOCKERFILE=") {
        $content = [regex]::Replace(
            $content,
            "(?m)^LOCAL_DOCKERFILE=.*$",
            "LOCAL_DOCKERFILE=$localDockerfile"
        )
    } else {
        if (-not $content.EndsWith("`n")) { $content += "`n" }
        $content += "LOCAL_DOCKERFILE=$localDockerfile`n"
    }
    [IO.File]::WriteAllText($envPath, $content, [Text.UTF8Encoding]::new($false))
}

Set-LocalDockerfileSetting
Set-LocalCredentialEmail

if ((Test-Path -LiteralPath $envPath) -and (Test-Path -LiteralPath $credentialsPath)) {
    Write-Output ".env.local već postoji; postojeće tajne nisu promenjene."
    exit 0
}

if (Test-Path -LiteralPath $envPath) {
    $adminPassword = ConvertTo-Base64Url (New-RandomBytes 24) $true
    $credentials = @{ email = $localAdminEmail; password = $adminPassword } | ConvertTo-Json
    [IO.File]::WriteAllText($credentialsPath, $credentials, [Text.UTF8Encoding]::new($false))
    Write-Output "Nedostajući lokalni test administratorski podaci su ponovo kreirani."
    exit 0
}

$secretKey = ConvertTo-Base64Url (New-RandomBytes 48) $true
$fernetKey = ConvertTo-Base64Url (New-RandomBytes 32) $false
$databasePassword = ConvertTo-Base64Url (New-RandomBytes 32) $true
$adminPassword = ConvertTo-Base64Url (New-RandomBytes 24) $true

$environment = @"
APP_ENV=development
APP_SECRET_KEY=$secretKey
APP_CREDENTIAL_ENCRYPTION_KEY=$fernetKey
APP_DATABASE_URL=postgresql+asyncpg://efakture:$databasePassword@db:5432/efakture
APP_ALLOWED_HOSTS=localhost,127.0.0.1
APP_CORS_ORIGINS=http://localhost:18080
APP_PUBLIC_BASE_URL=http://localhost:18080
APP_ACCESS_TOKEN_MINUTES=60
APP_LOGIN_MAX_ATTEMPTS=5
APP_LOGIN_WINDOW_SECONDS=900
APP_LOGIN_BLOCK_SECONDS=900
APP_PASSWORD_RESET_MINUTES=30
APP_SMTP_HOST=mailpit
APP_SMTP_PORT=1025
APP_SMTP_STARTTLS=false
APP_SMTP_FROM_EMAIL=noreply@local.test
APP_ARTIFACT_STORAGE_PATH=/data/artifacts
APP_MAX_ARTIFACT_BYTES=26214400
APP_WORKER_POLL_SECONDS=1
APP_WORKER_LOCK_TIMEOUT_SECONDS=300
APP_SYNC_INTERVAL_SECONDS=60
APP_SYNC_INITIAL_LOOKBACK_DAYS=1
APP_SYNC_OVERLAP_SECONDS=60
POSTGRES_PASSWORD=$databasePassword
LOCAL_DOCKERFILE=$localDockerfile
"@

[IO.File]::WriteAllText($envPath, $environment, [Text.UTF8Encoding]::new($false))
$credentials = @{
    email = $localAdminEmail
    password = $adminPassword
} | ConvertTo-Json
[IO.File]::WriteAllText($credentialsPath, $credentials, [Text.UTF8Encoding]::new($false))

Write-Output "Kreirani su .env.local i lokalni test administratorski podaci."
