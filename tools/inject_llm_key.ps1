# Inject a default LLM API key into an ALREADY-BUILT Windows bundle WITHOUT
# re-running the (heavy) packaging. It writes a ready-to-use backend\.env that
# carries the key, so the customer doesn't have to BYOK.
#
# Why this works: start.bat only copies .env.example -> .env when .env is
# MISSING. By placing a real backend\.env into the bundle, that file is used
# verbatim on first run (key already filled), and never overwritten.
#
# Targets either:
#   - an unzipped bundle folder ( ...\RLab Cortex\ )           → -Target <folder>
#   - the distributable zip ( dist\RLab Cortex-免安装-win64.zip ) → -Target <zip>
#
# Usage:
#   .\tools\inject_llm_key.ps1 -Key "sk-xxxx"
#   .\tools\inject_llm_key.ps1 -Key "sk-xxxx" -Target "D:\somewhere\RLab Cortex"
#   .\tools\inject_llm_key.ps1 -Key "sk-xxxx" -Target "dist\RLab Cortex-免安装-win64.zip"
#   # other providers:
#   .\tools\inject_llm_key.ps1 -Key "sk-xxxx" -BaseUrl "https://dashscope.aliyuncs.com/compatible-mode/v1" -Model "qwen-plus"

param(
  [Parameter(Mandatory = $true)][string]$Key,
  [string]$Target = "dist\RLab Cortex-免安装-win64.zip",
  [string]$Provider = "deepseek",
  [string]$BaseUrl = "https://api.deepseek.com/v1",
  [string]$Model = "deepseek-chat"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent

# Resolve target relative to repo root if not absolute.
if (-not [System.IO.Path]::IsPathRooted($Target)) { $Target = Join-Path $repoRoot $Target }
if (-not (Test-Path $Target)) { throw "target not found: $Target" }

# Generate a random 48-char SECRET_KEY so the packaged JWT signer isn't the
# shared placeholder (cheap security win while we're here).
$secret = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })

# The .env content. LF line-endings; UTF-8 no BOM (pydantic reads either, but
# keep it clean). Mirrors backend\.env.example with the key filled in.
$envLines = @(
  "APP_ENV=prod"
  "SECRET_KEY=$secret"
  "DATABASE_URL=sqlite+aiosqlite:///./data/db/app.db"
  "UPLOAD_DIR=./data/uploads"
  ""
  "# Default LLM key shipped with the bundle (billed to the vendor)."
  "LLM_PROVIDER=$Provider"
  "DEEPSEEK_API_KEY=$Key"
  "DEEPSEEK_BASE_URL=$BaseUrl"
  "DEEPSEEK_MODEL=$Model"
  ""
  "SANDBOX_CPU_SECONDS=10"
  "SANDBOX_MEMORY_MB=512"
  "SANDBOX_TIMEOUT_SECONDS=30"
  "SANDBOX_MAX_OUTPUT_BYTES=10485760"
  ""
  "CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000"
)
$envText = ($envLines -join "`n") + "`n"

$item = Get-Item $Target

if ($item.PSIsContainer) {
  # ── Folder bundle ──────────────────────────────────────────────────────────
  # Accept either ...\RLab Cortex or its parent; find the backend dir.
  $backend = if (Test-Path (Join-Path $Target "backend")) { Join-Path $Target "backend" }
             elseif (Test-Path (Join-Path $Target "RLab Cortex\backend")) { Join-Path $Target "RLab Cortex\backend" }
             else { throw "could not find backend\ under $Target" }
  $dest = Join-Path $backend ".env"
  [System.IO.File]::WriteAllText($dest, $envText, (New-Object System.Text.UTF8Encoding($false)))
  Write-Host "wrote $dest" -ForegroundColor Green
  Write-Host "Restart the bundle (stop.bat then start.bat) for it to take effect." -ForegroundColor Yellow
}
elseif ($item.Extension -ieq ".zip") {
  # ── Zip bundle ─────────────────────────────────────────────────────────────
  # Update the archive in place: add/replace the RLab Cortex/backend/.env entry.
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [System.IO.Compression.ZipFile]::Open($Target, [System.IO.Compression.ZipArchiveMode]::Update)
  try {
    # Detect the top-level folder name inside the zip (usually "RLab Cortex").
    $top = ($zip.Entries | Where-Object { $_.FullName -match '/' } |
            Select-Object -First 1).FullName.Split('/')[0]
    if (-not $top) { $top = "RLab Cortex" }
    $entryName = "$top/backend/.env"

    $existing = $zip.GetEntry($entryName)
    if ($existing) { $existing.Delete() }
    $entry = $zip.CreateEntry($entryName)
    $sw = New-Object System.IO.StreamWriter($entry.Open(), (New-Object System.Text.UTF8Encoding($false)))
    $sw.Write($envText)
    $sw.Dispose()
    Write-Host "injected $entryName into $Target" -ForegroundColor Green
  } finally {
    $zip.Dispose()
  }
  Write-Host "Done. Fresh unzips of this bundle will start with the key already set." -ForegroundColor Yellow
}
else {
  throw "target must be a folder or a .zip: $Target"
}
