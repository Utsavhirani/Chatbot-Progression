<#
One-command setup / health check for the AI Business Assistant (Windows PowerShell 5.1+).

  .\scripts\setup.ps1           first-time setup or update: checks, creates .env, builds, starts, verifies
  .\scripts\setup.ps1 -Check    only verify the environment and the running app (changes nothing)
  .\scripts\setup.ps1 -Fake     set up without an API key (simulated AI replies)
  .\scripts\setup.ps1 -Live     also send one real test message to the AI provider during verification

If script execution is blocked:  powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
#>
param([switch]$Check, [switch]$Fake, [switch]$Live)
# "Continue": in Windows PowerShell 5.1, "Stop" turns any stderr output of native programs (e.g. a
# harmless Docker warning) into a fatal error. Native commands are checked via $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Ok($m)   { Write-Host "  [ok]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red; exit 1 }
function Step($m) { Write-Host ""; Write-Host $m -ForegroundColor White }
function Get-EnvValue($key) {
    if (-not (Test-Path .env)) { return "" }
    $line = Get-Content .env | Where-Object { $_ -match "^$key=" } | Select-Object -Last 1
    if ($line) { return $line.Substring($key.Length + 1) } else { return "" }
}
function Set-EnvValue($key, $value) {
    $lines = @(Get-Content .env)
    $found = $false
    $lines = $lines | ForEach-Object { if ($_ -match "^$key=") { $found = $true; "$key=$value" } else { $_ } }
    if (-not $found) { $lines += "$key=$value" }
    # UTF-8 without BOM, LF line endings (read by Docker Compose and Python)
    [IO.File]::WriteAllText((Join-Path (Get-Location) ".env"), (($lines -join "`n") + "`n"))
}

Step "1. Prerequisites"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail "Docker is not installed. Install Docker Desktop: https://docs.docker.com/get-docker/" }
docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker is installed but not running. Start Docker Desktop and re-run." }
Ok ("Docker " + (docker version --format "{{.Server.Version}}") + " is running")
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 is missing (needs 'docker compose')." }
Ok (docker compose version)

Step "2. Configuration (.env)"
if (-not (Test-Path .env)) {
    if ($Check) { Fail ".env not found. Run .\scripts\setup.ps1 (without -Check) to create it." }
    Copy-Item .env.example .env
    $pw = [guid]::NewGuid().ToString("N")
    Set-EnvValue "POSTGRES_PASSWORD" $pw
    Set-EnvValue "DATABASE_URL" "postgresql+asyncpg://assistant:$pw@127.0.0.1:5433/assistant"
    Set-EnvValue "TEST_DATABASE_URL" "postgresql+asyncpg://assistant:$pw@127.0.0.1:5433/assistant_test"
    Ok "created .env with a random database password"
}
$key = Get-EnvValue "GROQ_API_KEY"
if (-not $Check -and -not $Fake -and (-not $key -or $key -eq "replace-me")) {
    if ($env:GROQ_API_KEY) { $key = $env:GROQ_API_KEY }
    else {
        $secure = Read-Host "  Enter your GroqCloud API key (free at https://console.groq.com/keys), or press Enter for simulated replies" -AsSecureString
        $key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    }
    if ($key) { Set-EnvValue "GROQ_API_KEY" $key; Set-EnvValue "PROVIDER" "groq"; Ok "API key saved to .env" }
    else { $Fake = $true }
}
if ($Fake -and -not $Check) {
    Set-EnvValue "PROVIDER" "fake"
    Warn "PROVIDER=fake: replies are simulated. Add GROQ_API_KEY to .env and re-run for real AI."
}
$webPort = $env:WEB_PORT; if (-not $webPort) { $webPort = Get-EnvValue "WEB_PORT" }; if (-not $webPort) { $webPort = "8080" }
Ok ("PROVIDER=" + (Get-EnvValue "PROVIDER") + ", web port $webPort")

$n = 3
if (-not $Check) {
    Step "$n. Build and start containers (first run takes a few minutes)"
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed (see output above)." }
    $n++
}

Step "$n. Waiting for the app to become healthy"; $n++
$state = ""
for ($i = 0; $i -lt 90; $i++) {
    $webId = (docker compose ps -q web 2>$null)
    $state = if ($webId) { (docker inspect -f "{{.State.Health.Status}}" $webId 2>$null) } else { "" }
    if ($state -eq "healthy") { break }
    if (-not $state -and $Check) { Fail "The app is not running. Start it with: docker compose up -d" }
    Start-Sleep -Seconds 2
}
if ($state -ne "healthy") { docker compose ps; Fail "The app did not become healthy. See: docker compose logs api" }
docker compose ps --format "    {{.Service}}: {{.Status}}"
Ok "containers healthy"

Step "$n. Self-check (configuration, database, AI provider)"
$doctorArgs = @("compose", "exec", "-T", "api", "python", "-m", "app.doctor")
if ($Live) { $doctorArgs += "--live" }
& docker @doctorArgs
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Ready! Open http://localhost:$webPort" -ForegroundColor Green
    Write-Host "Others on your network can use http://<this-computer-ip>:$webPort (see docs/sharing.md)."
} else {
    Fail "Self-check failed. Fix the items marked x above, then re-run: .\scripts\setup.ps1 -Check"
}
