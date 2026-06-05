@echo off
rem ============================================================================
rem  Numetrix backend launcher (double-click me)
rem
rem  Kills whatever holds :8077, then starts uvicorn from the venv. Reliable
rem  bits learned the hard way:
rem   * Kill by PORT, not by venv path: backend\.venv is a conda-delegating
rem     stub (pyvenv.cfg home = D:\TOOL\Conda), so the real server is an
rem     orphaned conda-python child. Only the :8077 listener pid is reliable.
rem   * Start in a MINIMIZED console window (not hidden): a real console is a
rem     valid stdout sink, so uvicorn doesn't wedge. App logs still go to
rem     tmp\backend.log via BACKEND_LOG_FILE (flushes every line).
rem   * If the FIRST import after a reboot / Defender update takes minutes, the
rem     venv isn't excluded from Defender. Run ONCE in an elevated PowerShell:
rem       Add-MpPreference -ExclusionPath 'd:\Git\Personal\DataAgent\backend\.venv'
rem ============================================================================
setlocal
title Numetrix backend launcher
set "REPO=%~dp0"
set "PY=%REPO%backend\.venv\Scripts\python.exe"
set "PORT=8077"
set "LOG=%REPO%tmp\backend.log"

if not exist "%PY%" (
  echo [ERROR] venv python not found: %PY%
  echo         create it first:  py -3 -m venv backend\.venv  ^&^&  pip install -r backend\requirements.txt
  pause
  exit /b 1
)
if not exist "%REPO%tmp" mkdir "%REPO%tmp"

echo == stopping any backend on :%PORT% ==
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort %PORT% -State Listen -EA SilentlyContinue | Select-Object -Expand OwningProcess -Unique; if($p){ $p | ForEach-Object { Write-Host ('   killing pid '+$_); Stop-Process -Id $_ -Force -EA SilentlyContinue } } else { Write-Host '   (none)' }"

rem cooldown so the socket + AV scanner release before we relaunch
powershell -NoProfile -Command "Start-Sleep -Seconds 2"

echo == starting backend ==
set "BACKEND_LOG_FILE=%LOG%"
set "PYTHONUNBUFFERED=1"
cd /d "%REPO%backend"
start "Numetrix Backend :%PORT%" /min "%PY%" -u -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --log-level info

echo == waiting for health (cold import can take a moment) ==
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 300;$i++){ try{ if((Invoke-WebRequest 'http://127.0.0.1:%PORT%/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){$ok=$true;break} }catch{}; Start-Sleep -Seconds 1 }; if($ok){ Write-Host ('   HEALTHY after '+$i+'s  ->  http://127.0.0.1:%PORT%') -Foreground Green } else { Write-Host '   NOT healthy in 300s - see tmp\backend.log' -Foreground Red }"

echo.
echo Backend runs in the minimized "Numetrix Backend" window. Log: %LOG%
echo To stop it, run stop-backend.bat (closing the window may leave an orphan).
echo.
pause
