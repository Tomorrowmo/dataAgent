@echo off
rem ============================================================================
rem  Numetrix full-stack launcher (double-click me) — backend :8077 + frontend :3000
rem
rem  Same reliable bits as start-backend.bat:
rem   * kill by PORT (venv is a conda-delegating stub; only the listener pid is reliable)
rem   * MINIMIZED console windows (real stdout sink, no wedge); backend logs to tmp\backend.log
rem   * if the first import after a reboot/Defender update takes minutes, exclude the venv once
rem     (elevated):  Add-MpPreference -ExclusionPath 'd:\Git\Personal\DataAgent\backend\.venv'
rem ============================================================================
setlocal
title Numetrix start-all
set "REPO=%~dp0"
set "PY=%REPO%backend\.venv\Scripts\python.exe"
set "BPORT=8077"
set "FPORT=3000"
set "LOG=%REPO%tmp\backend.log"

if not exist "%PY%" (
  echo [ERROR] venv python not found: %PY%
  pause & exit /b 1
)
if not exist "%REPO%web\node_modules" (
  echo [ERROR] web\node_modules missing - run once:  cd web  ^&^&  npm install
  pause & exit /b 1
)
if not exist "%REPO%tmp" mkdir "%REPO%tmp"

echo == stopping old backend (:%BPORT%) and frontend (:%FPORT%) ==
powershell -NoProfile -Command "foreach($port in %BPORT%,%FPORT%){ $p=Get-NetTCPConnection -LocalPort $port -State Listen -EA SilentlyContinue | Select-Object -Expand OwningProcess -Unique; if($p){ $p | ForEach-Object { Write-Host ('   killing pid '+$_+' on :'+$port); Stop-Process -Id $_ -Force -EA SilentlyContinue } } }"
powershell -NoProfile -Command "Start-Sleep -Seconds 2"

echo == starting backend ==
set "BACKEND_LOG_FILE=%LOG%"
set "PYTHONUNBUFFERED=1"
start "Numetrix Backend :%BPORT%" /min /D "%REPO%backend" "%PY%" -u -m uvicorn app.main:app --host 127.0.0.1 --port %BPORT% --log-level info

echo == starting frontend ==
start "Numetrix Frontend :%FPORT%" /min /D "%REPO%web" cmd /c "npm run dev"

echo == waiting for backend health (cold import can take a moment) ==
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 300;$i++){ try{ if((Invoke-WebRequest 'http://127.0.0.1:%BPORT%/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){$ok=$true;break} }catch{}; Start-Sleep -Seconds 1 }; if($ok){ Write-Host ('   backend HEALTHY after '+$i+'s') -Foreground Green } else { Write-Host '   backend NOT healthy in 300s - see tmp\backend.log' -Foreground Red }"

echo == waiting for frontend (:%FPORT% - first compile can take ~30s) ==
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 180;$i++){ if(Get-NetTCPConnection -LocalPort %FPORT% -State Listen -EA SilentlyContinue){$ok=$true;break}; Start-Sleep -Seconds 1 }; if($ok){ Write-Host ('   frontend listening after '+$i+'s') -Foreground Green } else { Write-Host '   frontend not up in 180s - check the Frontend window' -Foreground Yellow }"

echo.
echo   Backend : http://127.0.0.1:%BPORT%   (window "Numetrix Backend", log tmp\backend.log)
echo   Frontend: http://localhost:%FPORT%       (window "Numetrix Frontend")  ^<- open this in your browser
echo   Stop both: stop-all.bat
echo.
pause
