@echo off
chcp 65001 >nul
setlocal
title RLab Cortex
set "REPO=%~dp0"
set "PY=%REPO%runtime\python\python.exe"
set "NODE=%REPO%runtime\node\node.exe"
set "BPORT=8077"
set "FPORT=3000"
set "LOG=%REPO%backend\data\backend.log"

if not exist "%PY%" ( echo [ERROR] runtime\python ??????????? & pause & exit /b 1 )
if not exist "%NODE%" ( echo [ERROR] runtime\node ??????????? & pause & exit /b 1 )
if not exist "%REPO%backend\data" mkdir "%REPO%backend\data"
if not exist "%REPO%backend\.env" copy "%REPO%backend\.env.example" "%REPO%backend\.env" >nul

echo == stopping anything on :%BPORT% / :%FPORT% ==
powershell -NoProfile -Command "foreach($p in %BPORT%,%FPORT%){ $o=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue|Select-Object -Expand OwningProcess -Unique; if($o){$o|ForEach-Object{Stop-Process -Id $_ -Force -EA SilentlyContinue}} }"
powershell -NoProfile -Command "Start-Sleep -Seconds 2"

echo == starting backend (:%BPORT%) ==
set "BACKEND_LOG_FILE=%LOG%"
set "PYTHONUNBUFFERED=1"
start "RLab Cortex Backend" /min /D "%REPO%backend" "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %BPORT%

echo == starting frontend (:%FPORT%) ==
start "RLab Cortex Frontend" /min /D "%REPO%web" "%NODE%" node_modules\next\dist\bin\next start -p %FPORT%

echo == waiting for backend (cold start can take ~10-30s) ==
powershell -NoProfile -Command "for($i=0;$i -lt 300;$i++){try{if((Invoke-WebRequest 'http://127.0.0.1:%BPORT%/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){Write-Host ('   backend HEALTHY ('+$i+'s)') -Foreground Green;break}}catch{};Start-Sleep -Seconds 1}"
echo == waiting for frontend ==
powershell -NoProfile -Command "for($i=0;$i -lt 120;$i++){if(Get-NetTCPConnection -LocalPort %FPORT% -State Listen -EA SilentlyContinue){Write-Host ('   frontend up ('+$i+'s)') -Foreground Green;break};Start-Sleep -Seconds 1}"

start "" "http://localhost:%FPORT%"
echo.
echo   ?? http://localhost:%FPORT%        ??: stop.bat
echo.
pause
