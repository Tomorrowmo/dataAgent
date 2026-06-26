@echo off
chcp 65001 >nul
title RLab Cortex stop
echo == stopping backend (:8077) and frontend (:3000) ==
powershell -NoProfile -Command "foreach($p in 8077,3000){ $o=Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue|Select-Object -Expand OwningProcess -Unique; if($o){$o|ForEach-Object{Write-Host ('   killing pid '+$_+' on :'+$p);Stop-Process -Id $_ -Force -EA SilentlyContinue}} else {Write-Host ('   nothing on :'+$p)} }"
echo.
pause
