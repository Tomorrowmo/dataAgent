# Dev launcher: starts the backend in the background with a real log file.
#
# Why this exists / what kept biting us:
#
# 1. Start-Process -RedirectStandardOutput buffers writes inside the child on
#    Windows, so the log file stays at 0 bytes for minutes — invisible
#    debugging. We set BACKEND_LOG_FILE and let Python logging's
#    RotatingFileHandler flush on every emit. We STILL pass redirect files
#    because -WindowStyle Hidden without them wedges uvicorn's stdout sink.
#
# 2. THE REAL "启动老是卡" BUG: Windows Defender real-time scanning reads every
#    .pyc of numpy/pandas/scipy/sklearn on the first cold import. With the venv
#    NOT excluded, that first import has been observed taking 20+ MINUTES
#    (tmp/backend.log: "heavy imports done in 1237.00s"). Once warm it's ~1.3s.
#    So we add a Defender exclusion for the venv (best-effort; needs admin) —
#    that is the permanent fix. Everything below just makes the launcher
#    survive a slow cold start instead of making it worse.
#
# 3. Impatient re-runs used to stack competing cold imports: the old launcher
#    killed only the process LISTENING on the port, but a process still mid
#    cold-import hasn't bound the port yet, so a second run spawned a SECOND
#    cold import racing the first for AV bandwidth. We now kill via pidfile +
#    port + command-line match, so a re-run reliably reaps the prior instance.
#
# Usage:
#   .\tools\dev_backend.ps1          # restart (kills any prior instance)
#   .\tools\dev_backend.ps1 -Tail    # restart then tail the log
#   .\tools\dev_backend.ps1 -Stop    # stop, do not restart

param(
  [switch]$Tail,
  [switch]$Stop
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$logFile  = Join-Path $repoRoot "tmp\backend.log"
$pyExe    = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$venvDir  = Join-Path $repoRoot "backend\.venv"
$pidFile  = Join-Path $repoRoot "tmp\backend.pid"
$port     = 8077

function Is-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# 0. Ensure the venv is excluded from Defender real-time scanning. This is the
#    actual fix for the multi-minute cold-import hang. Set-MpPreference needs
#    admin; if we don't have it, print the one-time command to run elevated.
function Ensure-DefenderExclusion {
  try {
    $existing = (Get-MpPreference -ErrorAction Stop).ExclusionPath
  } catch {
    # Defender cmdlets unavailable (3rd-party AV, or Get-MpPreference blocked).
    Write-Host "note: could not query Defender ($($_.Exception.Message)) — skipping exclusion"
    return
  }
  if ($existing -and ($existing -contains $venvDir)) {
    return  # already excluded
  }
  if (Is-Admin) {
    try {
      Add-MpPreference -ExclusionPath $venvDir -ErrorAction Stop
      Write-Host "added Defender exclusion: $venvDir"
    } catch {
      Write-Host "could not add Defender exclusion ($($_.Exception.Message))"
    }
  } else {
    Write-Host ""
    Write-Host "*** ONE-TIME FIX for slow startup — run this ONCE in an elevated PowerShell: ***" -ForegroundColor Yellow
    Write-Host "    Add-MpPreference -ExclusionPath '$venvDir'"
    Write-Host "  Without it, the first import after a reboot / AV-definition update can take MINUTES." -ForegroundColor Yellow
    Write-Host ""
  }
}

# 1. Kill any prior backend instance. Three nets, fast → thorough:
#    (a) pidfile   — the instance THIS script launched last time, even if it's
#                    still mid cold-import and never bound the port.
#    (b) port      — whatever currently holds :8077 (e.g. a manual run).
#    (c) cmdline   — any python running our uvicorn module (best-effort; WMI
#                    can be slow on a contended box, so it's guarded + last).
function Stop-Backend {
  $pidsToKill = New-Object System.Collections.Generic.HashSet[int]

  # (a) pidfile
  if (Test-Path $pidFile) {
    try {
      $oldPid = [int](Get-Content $pidFile -ErrorAction Stop | Select-Object -First 1)
      $p = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
      if ($p -and $p.ProcessName -match 'python') { [void]$pidsToKill.Add($oldPid) }
    } catch {}
  }

  # (b) port listener
  try {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) { if ($c.OwningProcess -ne 0) { [void]$pidsToKill.Add([int]$c.OwningProcess) } }
  } catch {}

  # (c) any python whose EXE lives in OUR venv — catches an instance still
  #     mid cold-import that never bound the port and isn't in the pidfile.
  #     We match by .Path (fast, no WMI) instead of command line on purpose:
  #     Get-CimInstance/WMI can HANG indefinitely on a box choked by the very
  #     processes we're reaping (observed), and -OperationTimeoutSec doesn't
  #     save you if the WMI service connection itself wedges. Matching the venv
  #     path can ONLY hit our backend — never conda / MCP pythons.
  try {
    Get-Process python -ErrorAction SilentlyContinue |
      Where-Object { $_.Path -and $_.Path.StartsWith($venvDir, [System.StringComparison]::OrdinalIgnoreCase) } |
      ForEach-Object { [void]$pidsToKill.Add([int]$_.Id) }
  } catch {}

  foreach ($procId in $pidsToKill) {
    try { Stop-Process -Id $procId -Force -ErrorAction Stop; Write-Host "stopped backend pid $procId" }
    catch { Write-Host "could not stop pid $procId ($($_.Exception.Message))" }
  }
  if (Test-Path $pidFile) { Remove-Item $pidFile -ErrorAction SilentlyContinue }
}

Stop-Backend

if ($Stop) { Write-Host "stopped."; return }

Ensure-DefenderExclusion

# Cooldown: give Defender / the OS a moment to release file handles on the
# just-killed process before we spawn a fresh one (rapid restarts otherwise
# race the AV scanner and wedge).
Start-Sleep -Seconds 2

# 2. Make sure tmp/ exists
$tmpDir = Split-Path $logFile -Parent
if (-not (Test-Path $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir | Out-Null }

# 3. Launch uvicorn unbuffered, with file logging via BACKEND_LOG_FILE
$env:BACKEND_LOG_FILE = $logFile
$env:PYTHONUNBUFFERED = "1"

$workDir = Join-Path $repoRoot "backend"
$argList = @(
  "-u", "-m", "uvicorn", "app.main:app",
  "--host", "127.0.0.1",
  "--port", "$port",
  "--log-level", "info"
)

# These redirect files have to exist so the hidden child has a stdout sink
# (without them -WindowStyle Hidden wedges). We read tmp/backend.log instead.
$stdoutFile = Join-Path $tmpDir "uvicorn.out.log"
$stderrFile = Join-Path $tmpDir "uvicorn.err.log"

$proc = Start-Process -FilePath $pyExe -ArgumentList $argList `
  -WorkingDirectory $workDir `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdoutFile `
  -RedirectStandardError  $stderrFile `
  -PassThru

Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii
Write-Host "started backend pid $($proc.Id) on http://127.0.0.1:$port"
Write-Host "log:  $logFile"

# 4. Wait until /api/health responds. Deadline is generous (5 min) because a
#    cold import on a non-excluded venv can legitimately take minutes — we'd
#    rather wait than report a false failure and tempt an impatient re-run
#    (which stacks a competing cold import). We surface the latest log line
#    every few seconds so it's obvious the process is importing, not frozen.
$deadlineSec = 300
$deadline = (Get-Date).AddSeconds($deadlineSec)
$healthy = $false
$lastShown = ""
while ((Get-Date) -lt $deadline) {
  # Bail early if the process died outright.
  if ($proc.HasExited) {
    Write-Host "backend pid $($proc.Id) exited (code $($proc.ExitCode)) before serving — dumping stderr:" -ForegroundColor Red
    if (Test-Path $stderrFile) { Get-Content $stderrFile -Tail 40 }
    return
  }
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { Write-Host "healthy: $($r.Content)" -ForegroundColor Green; $healthy = $true; break }
  } catch {
    # Show import progress from the log so a slow cold start looks alive.
    if (Test-Path $logFile) {
      $tail = (Get-Content $logFile -Tail 1 -ErrorAction SilentlyContinue)
      if ($tail -and $tail -ne $lastShown) { Write-Host "  …$tail"; $lastShown = $tail }
    }
    Start-Sleep -Milliseconds 800
  }
}

if (-not $healthy) {
  Write-Host "backend did NOT pass health check within ${deadlineSec}s." -ForegroundColor Red
  Write-Host "If 'importing fastapi + heavy deps…' is the last log line, it's an AV cold-import — add the Defender exclusion above." -ForegroundColor Yellow
  if (Test-Path $logFile) { Get-Content $logFile -Tail 15 }
}

if ($Tail) {
  Write-Host "---- tailing $logFile (Ctrl+C to stop) ----"
  Get-Content $logFile -Wait -Tail 50
}
