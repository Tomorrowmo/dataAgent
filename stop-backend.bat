@echo off
rem Stop the RLab Cortex backend. Kills the process LISTENING on :8077 — that is
rem the (orphaned conda-python) server, which "close the window" may not reap.
setlocal
title RLab Cortex backend stop
set "PORT=8077"
echo == stopping backend on :%PORT% ==
powershell -NoProfile -Command "$p=Get-NetTCPConnection -LocalPort %PORT% -State Listen -EA SilentlyContinue | Select-Object -Expand OwningProcess -Unique; if($p){ $p | ForEach-Object { Write-Host ('   killing pid '+$_); Stop-Process -Id $_ -Force -EA SilentlyContinue } ; Write-Host '   stopped.' } else { Write-Host '   nothing listening on :%PORT%' }"
echo.
pause
