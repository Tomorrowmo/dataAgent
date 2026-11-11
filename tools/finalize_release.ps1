$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
$bundle = Join-Path $root 'dist\full\RLab Cortex'
$zip = Join-Path $root 'dist\DataAgent-安装包-win64.zip'

if (-not (Test-Path $bundle)) {
    throw "Bundle not found: $bundle"
}

if (Test-Path $zip) {
    Remove-Item $zip -Force
}

Compress-Archive -Path (Join-Path $bundle '*') -DestinationPath $zip -Force
Write-Host "ZIP_READY: $zip"
Get-Item $zip | Select-Object FullName,Length | Format-List

$py = Join-Path $bundle 'runtime\python\python.exe'
$node = Join-Path $bundle 'runtime\node\node.exe'

if (-not (Test-Path $py)) { throw "Missing Python runtime: $py" }
if (-not (Test-Path $node)) { throw "Missing Node runtime: $node" }

$backend = Start-Process -FilePath $py -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8077' -WorkingDirectory (Join-Path $bundle 'backend') -PassThru
$frontend = Start-Process -FilePath $node -ArgumentList 'node_modules\next\dist\bin\next','start','-p','3000' -WorkingDirectory (Join-Path $bundle 'web') -PassThru

$okBackend = $false
$okFrontend = $false

try {
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $status = (Invoke-WebRequest 'http://127.0.0.1:8077/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode
            if ($status -eq 200) {
                $okBackend = $true
                Write-Host "BACKEND_OK"
                break
            }
        }
        catch {
        }
        Start-Sleep -Seconds 1
    }

    for ($i = 0; $i -lt 60; $i++) {
        try {
            $r = Invoke-WebRequest 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) {
                $okFrontend = $true
                Write-Host 'FRONTEND_OK'
                break
            }
        }
        catch {
        }
        Start-Sleep -Seconds 1
    }

    if (-not $okBackend) { throw 'Backend health check failed.' }
    if (-not $okFrontend) { throw 'Frontend health check failed.' }
    Write-Host 'HEALTHCHECK_OK'
}
finally {
    Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
}
