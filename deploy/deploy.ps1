# Numetrix — Windows / local deploy helper using Docker Desktop.
# Usage:   pwsh -File deploy/deploy.ps1
# Optional env:  $env:DEEPSEEK_API_KEY = "sk-..."

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Info($m)  { Write-Host "==> $m" -ForegroundColor Yellow }
function OK($m)    { Write-Host " ✓ $m" -ForegroundColor Green  }
function Die($m)   { Write-Host " ✗ $m" -ForegroundColor Red; exit 1 }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Die "Docker is not installed or not on PATH" }
try { docker compose version | Out-Null } catch { Die "Docker Compose v2 plugin is required" }
OK "Docker ready"

if (-not (Test-Path "backend/.env")) {
  Info "Creating backend/.env"
  Copy-Item "backend/.env.example" "backend/.env"
}
if ($env:DEEPSEEK_API_KEY) {
  Info "Embedding DEEPSEEK_API_KEY into backend/.env"
  (Get-Content "backend/.env") -replace "^DEEPSEEK_API_KEY=.*$", "DEEPSEEK_API_KEY=$($env:DEEPSEEK_API_KEY)" | Set-Content "backend/.env" -Encoding utf8
}
if ((Get-Content "backend/.env") -match "dev-only-secret") {
  $secret = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
  (Get-Content "backend/.env") -replace "^SECRET_KEY=.*$", "SECRET_KEY=$secret" | Set-Content "backend/.env" -Encoding utf8
  OK "Rotated SECRET_KEY"
}

$port = if ($env:PUBLIC_PORT) { $env:PUBLIC_PORT } else { "8088" }
$origin = if ($env:PUBLIC_ORIGIN) { $env:PUBLIC_ORIGIN } else { "http://localhost:$port" }
$env:PUBLIC_PORT = $port
$env:PUBLIC_ORIGIN = $origin

Info "Building images"
docker compose -f deploy/docker-compose.yml build --pull
if ($LASTEXITCODE -ne 0) { Die "Build failed" }

Info "Starting the stack"
docker compose -f deploy/docker-compose.yml up -d
if ($LASTEXITCODE -ne 0) { Die "Compose up failed" }

Info "Waiting for the API to come up"
for ($i = 0; $i -lt 30; $i++) {
  try { Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 2 | Out-Null; OK "API is healthy"; break }
  catch { Start-Sleep -Seconds 2 }
}

Write-Host ""
Write-Host "====================================================================" -ForegroundColor Green
Write-Host "  Numetrix is live"                                                    -ForegroundColor Green
Write-Host "  URL:  http://localhost:$port"
Write-Host "====================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Logs:  docker compose -f deploy/docker-compose.yml logs -f"
Write-Host "  Stop:  docker compose -f deploy/docker-compose.yml down"
