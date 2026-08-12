param(
  [ValidateSet("start", "stop", "status", "logs")]
  [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$FrontendIndex = Join-Path $ProjectDir "frontend\dist\index.html"
$LogDir = Join-Path $ProjectDir "logs"
$PidFile = Join-Path $LogDir "erp.pid"
$OutLog = Join-Path $LogDir "erp.out.log"
$ErrLog = Join-Path $LogDir "erp.err.log"

function Get-ErpProcess {
  if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
  $savedPid = [int](Get-Content -LiteralPath $PidFile -Raw)
  return Get-Process -Id $savedPid -ErrorAction SilentlyContinue
}

function Stop-ErpProcessTree {
  param([int]$ProcessId)
  if ($IsWindows -or $env:OS -eq "Windows_NT") {
    & taskkill.exe /PID $ProcessId /T /F | Out-Null
  } else {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
  }
}

switch ($Action) {
  "start" {
    $running = Get-ErpProcess
    if ($running) { Write-Host "ERP is already running (PID $($running.Id))."; break }
    if (-not (Test-Path -LiteralPath $PythonExe) -or -not (Test-Path -LiteralPath $FrontendIndex)) {
      & (Join-Path $ProjectDir "setup.ps1")
    }
    & (Join-Path $ProjectDir "mysql-local.ps1") start
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    $arguments = @("-m", "uvicorn", "app.main:app", "--app-dir", (Join-Path $ProjectDir "backend"), "--host", "0.0.0.0", "--port", "8000")
    $process = Start-Process -FilePath $PythonExe -ArgumentList $arguments -WorkingDirectory $ProjectDir -WindowStyle Hidden -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru
    Set-Content -LiteralPath $PidFile -Value $process.Id
    Write-Host "ERP started (PID $($process.Id)): http://localhost:8000" -ForegroundColor Green
  }
  "stop" {
    $running = Get-ErpProcess
    if ($running) { Stop-ErpProcessTree -ProcessId $running.Id; Write-Host "ERP stopped." -ForegroundColor Yellow }
    else { Write-Host "ERP is not running." }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    & (Join-Path $ProjectDir "mysql-local.ps1") stop
  }
  "status" {
    $running = Get-ErpProcess
    if ($running) { Write-Host "ERP is running (PID $($running.Id))." -ForegroundColor Green }
    else { Write-Host "ERP is not running." -ForegroundColor Yellow }
  }
  "logs" {
    if (Test-Path -LiteralPath $ErrLog) { Get-Content -LiteralPath $ErrLog -Tail 80 }
    if (Test-Path -LiteralPath $OutLog) { Get-Content -LiteralPath $OutLog -Tail 80 }
  }
}
