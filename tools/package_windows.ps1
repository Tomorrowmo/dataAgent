# Build a portable Windows bundle of RLab Cortex (no installer needed).
#
# Output: dist\RLab Cortex-portable\  (a folder)  +  dist\RLab Cortex-portable.zip
#
# What it does: copies the source tree MINUS the regenerable / machine-specific /
# secret bits (venv, node_modules, .next, the local DB + uploads, .env, logs,
# git, docs), and drops in setup.bat / start.bat / stop.bat / 使用说明.txt.
#
# On the TARGET machine (Windows, online): unzip → run setup.bat once (creates a
# real venv, installs Python + web deps, production-builds the web) → start.bat.
# Prereqs on target: Python 3.11+ and Node.js 18+ on PATH (online install).
#
# Usage:  powershell -ExecutionPolicy Bypass -File tools\package_windows.ps1

$ErrorActionPreference = "Stop"
$root  = Split-Path $PSScriptRoot -Parent
$stage = Join-Path $root "dist\RLab Cortex-portable"
$zip   = Join-Path $root "dist\RLab Cortex-portable.zip"

Write-Host "Staging into $stage ..."
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# robocopy mirrors the tree; exit codes 0-7 are success (8+ is a real error).
# /XD = exclude dirs (matched by name anywhere), /XF = exclude files.
$xd = @('.git', '.claude', 'node_modules', '.venv', '.next', '__pycache__', 'tmp', 'data', 'dist', 'docs', '.vscode', '.idea')
$xf = @('*.log', '.env', '*.tsbuildinfo', '*.pyc', 'app.db', '*.zip')
robocopy $root $stage /E /XD $xd /XF $xf /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }
$global:LASTEXITCODE = 0

# docs/ is excluded wholesale, but the skill-pack authoring spec is served by the
# app itself (GET /api/skills/spec) — without it the 技能包 page has no "写法规范".
# Copy just that folder back in.
$docsSkills = Join-Path $root 'docs\skills'
if (Test-Path $docsSkills) {
  robocopy $docsSkills (Join-Path $stage 'docs\skills') /E /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy(docs\skills) failed with code $LASTEXITCODE" }
  $global:LASTEXITCODE = 0
}

# ── helper scripts shipped inside the bundle ────────────────────────────────
# .bat files: ASCII only (Chinese in echo breaks under the default code page);
# all Chinese guidance lives in 使用说明.txt (UTF-8).

$setup = @'
@echo off
chcp 65001 >nul
setlocal
title RLab Cortex setup
set "REPO=%~dp0"
echo === RLab Cortex one-time setup ===
echo.

where python >nul 2>&1
if errorlevel 1 ( echo [ERROR] Python not found. Install Python 3.11+ (check "Add to PATH"^) then re-run. & pause & exit /b 1 )
where npm >nul 2>&1
if errorlevel 1 ( echo [ERROR] Node.js not found. Install Node 18+ then re-run. & pause & exit /b 1 )

rem China mirrors (faster). Clear these two lines to use the official sources.
set "PIP_ARGS=-i https://pypi.tuna.tsinghua.edu.cn/simple"
set "NPM_REGISTRY=https://registry.npmmirror.com"

echo == [1/3] creating Python venv ==
if not exist "%REPO%backend\.venv\Scripts\python.exe" python -m venv "%REPO%backend\.venv"
if not exist "%REPO%backend\.venv\Scripts\python.exe" ( echo [ERROR] venv creation failed & pause & exit /b 1 )
set "PY=%REPO%backend\.venv\Scripts\python.exe"

echo == [2/3] installing Python deps (a few minutes) ==
"%PY%" -m pip install --upgrade pip %PIP_ARGS%
"%PY%" -m pip install -r "%REPO%backend\requirements.txt" %PIP_ARGS%
if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )

echo == [3/3] installing web deps + production build ==
pushd "%REPO%web"
call npm install --registry %NPM_REGISTRY%
if errorlevel 1 ( echo [ERROR] npm install failed & popd & pause & exit /b 1 )
call npm run build
if errorlevel 1 ( echo [ERROR] web build failed & popd & pause & exit /b 1 )
popd

if not exist "%REPO%backend\.env" copy "%REPO%backend\.env.example" "%REPO%backend\.env" >nul

echo.
echo === setup done. Double-click start.bat to launch. ===
pause
'@

$start = @'
@echo off
chcp 65001 >nul
setlocal
title RLab Cortex
set "REPO=%~dp0"
set "PY=%REPO%backend\.venv\Scripts\python.exe"
set "BPORT=8077"
set "FPORT=3000"
set "LOG=%REPO%tmp\backend.log"

if not exist "%PY%" ( echo [ERROR] Not set up yet - run setup.bat first. & pause & exit /b 1 )
if not exist "%REPO%web\.next" ( echo [ERROR] Web not built - run setup.bat first. & pause & exit /b 1 )
if not exist "%REPO%tmp" mkdir "%REPO%tmp"

echo == stopping anything on :%BPORT% / :%FPORT% ==
powershell -NoProfile -Command "foreach($p in %BPORT%,%FPORT%){ $o=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue|Select-Object -Expand OwningProcess -Unique; if($o){$o|ForEach-Object{Stop-Process -Id $_ -Force -EA SilentlyContinue}} }"
powershell -NoProfile -Command "Start-Sleep -Seconds 2"

echo == starting backend (:%BPORT%) ==
set "BACKEND_LOG_FILE=%LOG%"
set "PYTHONUNBUFFERED=1"
start "RLab Cortex Backend" /min /D "%REPO%backend" "%PY%" -u -m uvicorn app.main:app --host 127.0.0.1 --port %BPORT% --log-level info

echo == starting frontend (:%FPORT%, production) ==
start "RLab Cortex Frontend" /min /D "%REPO%web" cmd /c "npm start"

echo == waiting for backend health (cold import can take a moment) ==
powershell -NoProfile -Command "for($i=0;$i -lt 300;$i++){try{if((Invoke-WebRequest 'http://127.0.0.1:%BPORT%/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){Write-Host ('   backend HEALTHY ('+$i+'s)') -Foreground Green;break}}catch{};Start-Sleep -Seconds 1}"
echo == waiting for frontend ==
powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){if(Get-NetTCPConnection -LocalPort %FPORT% -State Listen -EA SilentlyContinue){Write-Host ('   frontend up ('+$i+'s)') -Foreground Green;break};Start-Sleep -Seconds 1}"

start "" "http://localhost:%FPORT%"
echo.
echo   Open: http://localhost:%FPORT%      Stop: stop.bat
echo.
pause
'@

$stop = @'
@echo off
chcp 65001 >nul
title RLab Cortex stop
echo == stopping backend (:8077) and frontend (:3000) ==
powershell -NoProfile -Command "foreach($p in 8077,3000){ $o=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue|Select-Object -Expand OwningProcess -Unique; if($o){$o|ForEach-Object{Write-Host ('   killing pid '+$_+' on :'+$p);Stop-Process -Id $_ -Force -EA SilentlyContinue}} else {Write-Host ('   nothing on :'+$p)} }"
echo.
pause
'@

$readme = @'
RLab Cortex 便携包（Windows）
==========================

前置条件（目标机器只需装这两个，联网即可）：
  1. Python 3.11+    https://www.python.org/downloads/  （安装时务必勾选 "Add Python to PATH"）
  2. Node.js 18+     https://nodejs.org/                 （LTS 版即可）

第一次使用：
  1. 把本文件夹整个解压到任意位置（路径建议别含空格/中文最稳妥，但一般也行）。
  2. 双击  setup.bat  ——会自动建 Python 虚拟环境、装依赖、构建前端（约 3~8 分钟，看网速）。
     （脚本默认用清华 pip 源 + npmmirror 国内镜像加速；想用官方源就编辑 setup.bat 把那两行清空）
  3. 完成后双击  start.bat  ——自动启动后端(:8077)+前端(:3000)，并打开浏览器到 http://localhost:3000

日常使用：
  - 启动：双击 start.bat
  - 停止：双击 stop.bat
  - 后端日志：tmp\backend.log

关于 AI 功能（解析未知格式 / AI 解释 / 对话分析）：
  - 这些功能要调用大模型。首次进入后注册一个账号，到「设置」里填一个模型的 API Key
    （DeepSeek 或任意 OpenAI 兼容接口都行）。Key 算在你自己账上。
  - 不填 Key 也能用：导入数据、自动“认识这份数据”、内置算法、数据表预览/排序/筛选、
    示例数据与示例流程，都不需要联网模型。

数据存哪：
  - 全部在本机 backend\data\ 下（SQLite + 上传的文件）。换机器/备份直接拷这个目录。
  - 本便携包不含任何已有数据，是干净的全新实例；新注册的账号会自动带几个示例数据集和流程。

通过域名访问（公网域名 + 自动 HTTPS）：
  架构：浏览器 https://你的域名 → Caddy(:80/:443) → 前端(:3000) → /api 转发到后端(:8077)
  前提（缺一不可）：
    1) 这台机器有公网 IP，且 80 和 443 端口对公网开放（Windows 防火墙 + 路由器都要放行）
    2) 在域名服务商把该域名的 A 记录指向这台机器的公网 IP
  步骤：
    1) 先正常 start.bat 把应用跑起来（:3000）
    2) 右键 serve-domain.bat →“以管理员身份运行”，按提示输入你的域名
       （首次会自动下载 caddy.exe，并为你的域名自动申请 Let's Encrypt 证书）
    3) 浏览器打开 https://你的域名 即可
  说明：
    - 证书自动续期，不用管。停止反代：在 Caddy 窗口按 Ctrl+C。
    - 如果机器在内网/NAT 后面、没有公网 IP，证书申请会失败——需要先做端口映射(80/443)，
      或改用内网穿透(Cloudflare Tunnel / frp 等)把域名引到本机。

网格/CFD 文件支持（可选）：
  - 上传 .cgns / .vtk / .vtu / .stl 这类 3D 网格文件需要额外的 pyvista(含 VTK，较大)。
  - 需要时在 backend 目录跑：  .venv\Scripts\python -m pip install pyvista
  - 只用 CSV / Excel / Parquet / Tecplot(.dat) 的话不需要它。

注意：
  - 如果第一次启动后端卡很久（几分钟没 HEALTHY），通常是 Windows Defender 在扫 venv。
    用管理员 PowerShell 跑一次（把路径换成你的实际路径）即可永久解决：
      Add-MpPreference -ExclusionPath "解压路径\backend\.venv"
'@

# ── public-domain reverse proxy via Caddy (auto-HTTPS) ──────────────────────
# Caddy reads {$DOMAIN} from the environment, so the Caddyfile is static and the
# .bat just sets DOMAIN. Caddy auto-obtains + renews a Let's Encrypt cert as long
# as the domain points here and :80/:443 are reachable from the internet.
$caddyfile = @'
# RLab Cortex public reverse proxy. DOMAIN is provided by serve-domain.bat.
{$DOMAIN} {
    encode zstd gzip
    reverse_proxy 127.0.0.1:3000
}
'@

$servedomain = @'
@echo off
chcp 65001 >nul
setlocal
title RLab Cortex domain proxy (Caddy)
set "REPO=%~dp0"

echo === 通过域名访问 (Caddy 反向代理 + 自动 HTTPS) ===
echo 前提: 1) start.bat 已在运行(:3000)  2) 本机有公网IP且 80/443 已放行  3) 域名A记录已指向本机
echo 建议右键“以管理员身份运行”(绑定 80/443 可能需要管理员权限)。
echo.
set /p DOMAIN=请输入你的域名(例如 numetrix.example.com):
if "%DOMAIN%"=="" ( echo [ERROR] 域名不能为空 & pause & exit /b 1 )

if not exist "%REPO%caddy\caddy.exe" (
  echo == 正在下载 Caddy ... ==
  powershell -NoProfile -Command "try{ Invoke-WebRequest 'https://caddyserver.com/api/download?os=windows&arch=amd64' -OutFile '%REPO%caddy\caddy.exe' -UseBasicParsing }catch{ Write-Host ('下载失败: '+$_.Exception.Message) -Foreground Red; exit 1 }"
)
if not exist "%REPO%caddy\caddy.exe" ( echo [ERROR] 未拿到 caddy.exe，请手动从 https://caddyserver.com/download 下载放到 caddy\ 目录 & pause & exit /b 1 )

echo.
echo == 启动 Caddy，为 %DOMAIN% 自动申请/续期 HTTPS 证书 ==
echo    访问: https://%DOMAIN%      停止: 在本窗口按 Ctrl+C
echo.
"%REPO%caddy\caddy.exe" run --config "%REPO%caddy\Caddyfile" --adapter caddyfile
pause
'@

New-Item -ItemType Directory -Force -Path (Join-Path $stage 'caddy') | Out-Null
Set-Content -Path (Join-Path $stage 'caddy\Caddyfile') -Value $caddyfile -Encoding ascii
Set-Content -Path (Join-Path $stage 'serve-domain.bat') -Value $servedomain -Encoding ascii

Set-Content -Path (Join-Path $stage 'setup.bat') -Value $setup -Encoding ascii
Set-Content -Path (Join-Path $stage 'start.bat') -Value $start -Encoding ascii
Set-Content -Path (Join-Path $stage 'stop.bat')  -Value $stop  -Encoding ascii
Set-Content -Path (Join-Path $stage '使用说明.txt') -Value $readme -Encoding utf8

# Remove the dev-only launchers so users aren't confused (start.bat is the one).
foreach ($f in 'start-all.bat','start-backend.bat','stop-all.bat','stop-backend.bat') {
  $p = Join-Path $stage $f
  if (Test-Path $p) { Remove-Item $p -Force }
}

Write-Host "Zipping → $zip ..."
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip

$sizeMB = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "Done. Portable bundle:" -ForegroundColor Green
Write-Host "  folder: $stage"
Write-Host "  zip   : $zip  ($sizeMB MB)"
Write-Host "Copy the zip to the target machine, unzip, run setup.bat then start.bat."
