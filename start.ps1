$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$FrontendIndex = Join-Path $ProjectDir "frontend\dist\index.html"

if (-not (Test-Path -LiteralPath $PythonExe) -or -not (Test-Path -LiteralPath $FrontendIndex)) {
  & (Join-Path $ProjectDir "setup.ps1")
}

Write-Host "Lite ERP: http://localhost:8000" -ForegroundColor Cyan
Write-Host "API docs: http://localhost:8000/docs" -ForegroundColor DarkGray
& $PythonExe -m uvicorn app.main:app --app-dir (Join-Path $ProjectDir "backend") --host 0.0.0.0 --port 8000

