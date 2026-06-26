@echo off
rem Stop both the RLab Cortex backend (:8077) and frontend (:3000) by killing the
rem processes LISTENING on those ports (closing the windows may leave orphans).
setlocal
title RLab Cortex stop-all
echo == stopping backend (:8077) and frontend (:3000) ==
powershell -NoProfile -Command "foreach($port in 8077,3000){ $p=Get-NetTCPConnection -LocalPort $port -State Listen -EA SilentlyContinue | Select-Object -Expand OwningProcess -Unique; if($p){ $p | ForEach-Object { Write-Host ('   killing pid '+$_+' on :'+$port); Stop-Process -Id $_ -Force -EA SilentlyContinue } } else { Write-Host ('   nothing on :'+$port) } }"
echo.
pause
