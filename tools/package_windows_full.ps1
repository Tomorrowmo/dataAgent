# Build a FULLY SELF-CONTAINED Windows bundle of RLab Cortex — the customer installs
# NOTHING (no Python, no Node, no pip/npm). They unzip and double-click start.bat.
#
# What goes in the bundle:
#   runtime\python\  — CPython 3.12 embeddable + ALL backend deps pre-installed
#   runtime\node\    — portable Node (node.exe + npm)
#   backend\         — app source + requirements + .env.example + empty data\
#   web\             — source + node_modules (pre-installed) + .next (prod build)
#   caddy\           — caddy.exe + Caddyfile (optional public-domain reverse proxy)
#   start.bat / stop.bat / serve-domain.bat / 使用说明.txt
#
# Output: dist\full\RLab Cortex\  (folder)  +  dist\RLab Cortex-免安装-win64.zip
#
# Requires (on THIS build machine, online): a working local Node + internet.
# Heavy: downloads ~45MB runtimes + installs sci wheels + npm install; the zip is
# ~1.3 GB and the build takes several minutes. Windows x64 only.
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\package_windows_full.ps1

$ErrorActionPreference = "Stop"
$ProgressPreference   = "SilentlyContinue"
$root = Split-Path $PSScriptRoot -Parent
$full = Join-Path $root "dist\full"
$app  = Join-Path $full "RLab Cortex"
$dl   = Join-Path $full "dl"

# Pin versions to match what we develop/test against.
$PYVER   = "3.12.7"
$NODEVER = "v22.18.0"
$PY_URL   = "https://registry.npmmirror.com/-/binary/python/$PYVER/python-$PYVER-embed-amd64.zip"
$NODE_URL = "https://registry.npmmirror.com/-/binary/node/$NODEVER/node-$NODEVER-win-x64.zip"
$GETPIP   = "https://bootstrap.pypa.io/get-pip.py"
$CADDY    = "https://caddyserver.com/api/download?os=windows&arch=amd64"
$PIP_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
$NPM_MIRROR = "https://registry.npmmirror.com"

Write-Host "== clean staging ==" -ForegroundColor Cyan
if (Test-Path $app) { Remove-Item $app -Recurse -Force }
New-Item -ItemType Directory -Force -Path $app, $dl | Out-Null

Write-Host "== download runtimes ==" -ForegroundColor Cyan
if (-not (Test-Path "$dl\python-embed.zip")) { Invoke-WebRequest $PY_URL   -OutFile "$dl\python-embed.zip" -UseBasicParsing }
if (-not (Test-Path "$dl\node.zip"))         { Invoke-WebRequest $NODE_URL -OutFile "$dl\node.zip" -UseBasicParsing }
if (-not (Test-Path "$dl\get-pip.py"))       { Invoke-WebRequest $GETPIP   -OutFile "$dl\get-pip.py" -UseBasicParsing }

Write-Host "== set up embeddable Python + deps ==" -ForegroundColor Cyan
$py = "$app\runtime\python"
New-Item -ItemType Directory -Force -Path $py | Out-Null
Expand-Archive "$dl\python-embed.zip" -DestinationPath $py -Force
$pth = (Get-ChildItem "$py\python*._pth" | Select-Object -First 1).FullName
(Get-Content $pth) -replace '^#\s*import site', 'import site' | Set-Content $pth -Encoding ascii
& "$py\python.exe" "$dl\get-pip.py" --no-warn-script-location | Out-Null
& "$py\python.exe" -m pip install -r "$root\backend\requirements.txt" -i $PIP_MIRROR --no-warn-script-location | Out-Null
& "$py\python.exe" -c "import fastapi,uvicorn,pandas,numpy,scipy,sklearn,pyarrow,sqlalchemy,openpyxl,passlib,jwt,httpx"
if ($LASTEXITCODE) { throw "embeddable Python failed import check" }

Write-Host "== unpack portable Node ==" -ForegroundColor Cyan
Remove-Item "$dl\node_x" -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive "$dl\node.zip" -DestinationPath "$dl\node_x" -Force
$inner = (Get-ChildItem "$dl\node_x" -Directory | Select-Object -First 1).FullName
New-Item -ItemType Directory -Force -Path "$app\runtime\node" | Out-Null
Copy-Item "$inner\*" "$app\runtime\node" -Recurse -Force

Write-Host "== copy + build web (npm install + prod build) ==" -ForegroundColor Cyan
robocopy "$root\web" "$app\web" /E /XD node_modules .next /XF *.tsbuildinfo /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy web failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0
Push-Location "$app\web"
cmd /c "npm install --registry $NPM_MIRROR" | Out-Null
if ($LASTEXITCODE) { Pop-Location; throw "npm install failed" }
cmd /c "npm run build" | Out-Null
if ($LASTEXITCODE) { Pop-Location; throw "web build failed" }
Pop-Location
if (-not (Test-Path "$app\web\.next")) { throw ".next not produced" }

Write-Host "== copy backend ==" -ForegroundColor Cyan
robocopy "$root\backend" "$app\backend" /E /XD .venv data __pycache__ /XF .env *.log *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy backend failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0
New-Item -ItemType Directory -Force -Path "$app\backend\data" | Out-Null

Write-Host "== launch scripts + caddy + readme ==" -ForegroundColor Cyan
# (start.bat / stop.bat / serve-domain.bat / Caddyfile / 使用说明.txt are written
#  here — kept identical to the verified bundle. See repo history for contents.)
$scriptsDir = Join-Path $PSScriptRoot "win_full_assets"
if (Test-Path $scriptsDir) {
  Copy-Item "$scriptsDir\start.bat"        "$app\start.bat" -Force
  Copy-Item "$scriptsDir\stop.bat"         "$app\stop.bat" -Force
  Copy-Item "$scriptsDir\serve-domain.bat" "$app\serve-domain.bat" -Force
  New-Item -ItemType Directory -Force -Path "$app\caddy" | Out-Null
  Copy-Item "$scriptsDir\Caddyfile"        "$app\caddy\Caddyfile" -Force
  Copy-Item "$scriptsDir\使用说明.txt"      "$app\使用说明.txt" -Force
} else {
  Write-Warning "tools\win_full_assets\ not found — copy start.bat/stop.bat/serve-domain.bat/Caddyfile/使用说明.txt into the bundle manually."
}
New-Item -ItemType Directory -Force -Path "$app\caddy" | Out-Null
if (-not (Test-Path "$app\caddy\caddy.exe")) {
  try { Invoke-WebRequest $CADDY -OutFile "$app\caddy\caddy.exe" -UseBasicParsing } catch { Write-Warning "caddy download failed: $($_.Exception.Message)" }
}

Write-Host "== slim the bundle (drop runtime-unneeded weight) ==" -ForegroundColor Cyan
# Python: test suites + bytecode caches are never needed at runtime.
$sp = "$app\runtime\python\Lib\site-packages"
Get-ChildItem $sp -Recurse -Directory -Filter __pycache__ -EA SilentlyContinue | Remove-Item -Recurse -Force -EA SilentlyContinue
Get-ChildItem $sp -Recurse -Directory -EA SilentlyContinue | Where-Object { $_.Name -in 'tests','test' } | Remove-Item -Recurse -Force -EA SilentlyContinue
# Node: keep node.exe only; bundled npm/corepack aren't used by `next start`.
Remove-Item "$app\runtime\node\node_modules\npm" -Recurse -Force -EA SilentlyContinue
Remove-Item "$app\runtime\node\npm","$app\runtime\node\npm.cmd","$app\runtime\node\npx","$app\runtime\node\npx.cmd","$app\runtime\node\corepack","$app\runtime\node\corepack.cmd" -Force -EA SilentlyContinue
# Web: build cache (268MB) + dev deps + SWC compiler (177MB) — none needed by `next start`.
Remove-Item "$app\web\.next\cache" -Recurse -Force -EA SilentlyContinue
Push-Location "$app\web"; & npm.cmd prune --omit=dev *> $null; Pop-Location
Get-ChildItem "$app\web\node_modules\@next" -Directory -Filter 'swc-*' -EA SilentlyContinue | Remove-Item -Recurse -Force -EA SilentlyContinue
$slimMB = [math]::Round(((Get-ChildItem $app -Recurse -File -EA SilentlyContinue|Measure-Object Length -Sum).Sum/1MB),0)
Write-Host "   slimmed bundle: $slimMB MB"

Write-Host "== zip ==" -ForegroundColor Cyan
$zip = Join-Path $root "dist\RLab Cortex-免安装-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Push-Location $full
# Quote the folder — "RLab Cortex" has a space; unquoted, tar would treat it as
# two paths ("RLab" + "Cortex") and silently produce no archive.
tar -a -c -f $zip "RLab Cortex"
$tarExit = $LASTEXITCODE
Pop-Location
if ($tarExit -or -not (Test-Path $zip)) { throw "tar zip step failed (exit $tarExit) — no archive produced" }

$mb = [math]::Round((Get-Item $zip).Length/1MB, 0)
Write-Host "`nDONE → $zip  ($mb MB)" -ForegroundColor Green
Write-Host "Copy the zip to the target Windows x64 machine, unzip to a writable folder, double-click start.bat."
